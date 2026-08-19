from __future__ import annotations

from typing import Any

from mail_agent_core.agent import MailAgent, MailMessageContext, ThreadMessageContext
from mail_agent_core.behavior import apply_rule_overrides, behavior_is_active, matching_rule
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentBehaviorSettings,
    AgentProfile,
    MailActionType,
    RuleMode,
)

from .action_executor import MailActionExecutor
from .audit import AuditLog
from .mail_store import MailStore
from .state import JsonStateStore

_REMOTE_MUTATIONS = {
    MailActionType.MARK_READ,
    MailActionType.MOVE,
    MailActionType.ARCHIVE,
}


class AgentRuntime:
    def __init__(
        self,
        *,
        mail_agent: MailAgent,
        identity_manager: IdentityManager,
        mail_store: MailStore,
        state_store: JsonStateStore,
        providers: dict[str, Any],
        audit_log: AuditLog,
        action_executor: MailActionExecutor | None = None,
    ):
        self.mail_agent = mail_agent
        self.identity_manager = identity_manager
        self.mail_store = mail_store
        self.state_store = state_store
        self.providers = providers
        self.audit_log = audit_log
        self.action_executor = action_executor

    def _configuration(self) -> dict[str, Any]:
        state = self.state_store.read()
        config = state.get("configuration")
        if not state.get("onboarding_completed") or not isinstance(config, dict):
            raise RuntimeError("Onboarding is not complete")
        return config

    @staticmethod
    def behavior(config: dict[str, Any]) -> AgentBehaviorSettings:
        return AgentBehaviorSettings.model_validate(config.get("behavior") or {})

    def _with_thread_context(
        self,
        message: MailMessageContext,
        behavior: AgentBehaviorSettings,
    ) -> MailMessageContext:
        if message.thread_context or not message.thread_id or behavior.thread_context_messages == 0:
            return message
        stored = self.mail_store.list_thread_messages(
            message.mailbox_id,
            message.thread_id,
            limit=behavior.thread_context_messages,
            exclude_message_id=message.message_id,
        )
        context = [
            ThreadMessageContext(
                message_id=str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid")),
                sender=str(item.get("sender") or ""),
                recipients=list(item.get("recipients") or []),
                subject=str(item.get("subject") or ""),
                body=str(item.get("body_text") or ""),
                sent_at=item.get("sent_at"),
            )
            for item in stored
        ]
        return message.model_copy(update={"thread_context": context})

    async def analyze_message(
        self,
        message: MailMessageContext,
        *,
        create_artifacts: bool = True,
        minimum_confidence: float | None = None,
    ) -> dict[str, Any]:
        config = self._configuration()
        provider_name = str(config["provider"])
        provider = self.providers.get(provider_name)
        if provider is None:
            raise RuntimeError("Configured provider is unavailable")
        identity = self.identity_manager.load()
        profile = AgentProfile.model_validate(config["profile"])
        behavior = self.behavior(config)
        threshold = behavior.minimum_confidence if minimum_confidence is None else minimum_confidence
        message = self._with_thread_context(message, behavior)

        analysis = await self.mail_agent.analyze(
            profile=profile,
            provider=provider,
            model=str(config["model"]),
            message=message,
            identity=identity,
            sign_payload=self.identity_manager.sign,
        )

        rule_mode, priority, category = apply_rule_overrides(
            sender=message.sender,
            settings=behavior,
            priority=analysis.proposal.priority,
            category=analysis.proposal.category,
        )
        analysis.proposal.priority = priority
        analysis.proposal.category = category

        if rule_mode == RuleMode.DRAFT_ONLY and analysis.proposal.action in {
            MailActionType.SEND_REPLY,
            MailActionType.FORWARD,
        }:
            metadata = dict(analysis.proposal.metadata)
            metadata["drafted_from_action"] = analysis.proposal.action.value
            analysis.proposal.metadata = metadata
            analysis.proposal.action = MailActionType.CREATE_DRAFT
            analysis.policy = self.mail_agent.policy_engine.evaluate(profile, analysis.proposal)

        self.mail_store.update_message_intelligence(
            message.mailbox_id,
            message.message_id,
            priority=analysis.proposal.priority.value,
            category=analysis.proposal.category.value,
            summary=analysis.proposal.summary,
            needs_reply=analysis.proposal.needs_reply,
        )

        approval = None
        draft = None
        execution = None
        confidence_ok = analysis.proposal.confidence >= threshold
        artifacts_allowed = rule_mode not in {RuleMode.ANALYZE_ONLY, RuleMode.IGNORE}
        if create_artifacts and artifacts_allowed and confidence_ok and analysis.policy.allowed:
            if analysis.policy.requires_approval:
                approval = self.mail_store.enqueue_approval(analysis.proposal, analysis.policy)
            elif analysis.proposal.action in _REMOTE_MUTATIONS:
                if self.action_executor is None:
                    raise RuntimeError("Remote action executor is not configured")
                execution = await self.action_executor.execute_direct(analysis.proposal)
            if (
                behavior.auto_create_drafts
                and analysis.proposal.body
                and analysis.proposal.action.value in {"create_draft", "send_reply", "forward"}
            ):
                draft = self.mail_store.create_draft(
                    analysis.proposal,
                    approval_id=approval["approval_id"] if approval else None,
                )

        payload = analysis.model_dump(mode="json")
        payload["approval"] = approval
        payload["draft"] = draft
        payload["execution"] = execution
        payload["confidence_threshold"] = threshold
        payload["confidence_accepted"] = confidence_ok
        payload["rule_mode"] = rule_mode.value
        return payload

    async def run_mailbox(self, mailbox_id: str, *, force: bool = False) -> dict[str, Any]:
        config = self._configuration()
        behavior = self.behavior(config)
        if not force:
            if not behavior.enabled or not behavior.auto_analyze_new_mail:
                return {"mailbox_id": mailbox_id, "processed": 0, "skipped": "agent_disabled"}
            if not behavior_is_active(behavior):
                return {"mailbox_id": mailbox_id, "processed": 0, "skipped": "outside_schedule"}

        messages = self.mail_store.list_messages(mailbox_id, behavior.max_messages_per_cycle)
        processed = 0
        ignored = 0
        urgent = 0
        drafts = 0
        approvals = 0
        executed = 0
        below_confidence = 0
        errors = 0
        for item in reversed(messages):
            message_id = str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid"))
            if self.mail_store.is_agent_processed(mailbox_id, message_id):
                continue
            rule = matching_rule(str(item.get("sender") or ""), behavior)
            if rule is not None and rule.mode == RuleMode.IGNORE:
                self.mail_store.record_agent_processing(mailbox_id, message_id, status="ignored_rule")
                ignored += 1
                continue
            context = MailMessageContext(
                mailbox_id=mailbox_id,
                message_id=message_id,
                thread_id=str(item.get("thread_key") or "") or None,
                sender=str(item.get("sender") or ""),
                recipients=list(item.get("recipients") or []),
                subject=str(item.get("subject") or ""),
                body=str(item.get("body_text") or ""),
                sent_at=item.get("sent_at"),
            )
            try:
                result = await self.analyze_message(context, create_artifacts=True)
                proposal = result["proposal"]
                if proposal.get("priority") == "urgent":
                    urgent += 1
                if not result["confidence_accepted"]:
                    below_confidence += 1
                    status = "below_confidence"
                else:
                    status = "processed"
                    drafts += 1 if result.get("draft") else 0
                    approvals += 1 if result.get("approval") else 0
                    executed += 1 if result.get("execution") else 0
                self.mail_store.record_agent_processing(
                    mailbox_id,
                    message_id,
                    status=status,
                    proposal_action=proposal.get("action"),
                    confidence=float(proposal.get("confidence") or 0.0),
                )
                processed += 1
            except Exception as exc:
                errors += 1
                self.mail_store.record_agent_processing(
                    mailbox_id,
                    message_id,
                    status="error",
                    error=str(exc),
                )
                self.audit_log.append(
                    "agent_message_failed",
                    details={"mailbox_id": mailbox_id, "message_id": message_id, "error": str(exc)},
                )

        summary = {
            "mailbox_id": mailbox_id,
            "processed": processed,
            "ignored": ignored,
            "urgent": urgent,
            "drafts": drafts,
            "approvals": approvals,
            "executed": executed,
            "below_confidence": below_confidence,
            "errors": errors,
        }
        self.audit_log.append("agent_cycle_completed", details=summary)
        return summary