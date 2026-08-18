from __future__ import annotations

from typing import Any

from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.behavior import behavior_is_active, sender_matches
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentBehaviorSettings, AgentProfile

from .audit import AuditLog
from .mail_store import MailStore
from .state import JsonStateStore


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
    ):
        self.mail_agent = mail_agent
        self.identity_manager = identity_manager
        self.mail_store = mail_store
        self.state_store = state_store
        self.providers = providers
        self.audit_log = audit_log

    def _configuration(self) -> dict[str, Any]:
        state = self.state_store.read()
        config = state.get("configuration")
        if not state.get("onboarding_completed") or not isinstance(config, dict):
            raise RuntimeError("Onboarding is not complete")
        return config

    @staticmethod
    def behavior(config: dict[str, Any]) -> AgentBehaviorSettings:
        return AgentBehaviorSettings.model_validate(config.get("behavior") or {})

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

        analysis = await self.mail_agent.analyze(
            profile=profile,
            provider=provider,
            model=str(config["model"]),
            message=message,
            identity=identity,
        )

        approval = None
        draft = None
        confidence_ok = analysis.proposal.confidence >= threshold
        if create_artifacts and confidence_ok and analysis.policy.allowed:
            if analysis.policy.requires_approval:
                approval = self.mail_store.enqueue_approval(analysis.proposal, analysis.policy)
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
        payload["confidence_threshold"] = threshold
        payload["confidence_accepted"] = confidence_ok
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
        drafts = 0
        approvals = 0
        below_confidence = 0
        errors = 0
        for item in reversed(messages):
            message_id = str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid"))
            if self.mail_store.is_agent_processed(mailbox_id, message_id):
                continue
            if sender_matches(str(item.get("sender") or ""), behavior.never_auto_act_senders):
                self.mail_store.record_agent_processing(mailbox_id, message_id, status="blocked_sender")
                continue
            context = MailMessageContext(
                mailbox_id=mailbox_id,
                message_id=message_id,
                thread_id=str(item.get("thread_key") or "") or None,
                sender=str(item.get("sender") or ""),
                recipients=list(item.get("recipients") or []),
                subject=str(item.get("subject") or ""),
                body=str(item.get("body_text") or ""),
            )
            try:
                result = await self.analyze_message(context, create_artifacts=True)
                proposal = result["proposal"]
                if not result["confidence_accepted"]:
                    below_confidence += 1
                    status = "below_confidence"
                else:
                    status = "processed"
                    drafts += 1 if result.get("draft") else 0
                    approvals += 1 if result.get("approval") else 0
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
            "drafts": drafts,
            "approvals": approvals,
            "below_confidence": below_confidence,
            "errors": errors,
        }
        self.audit_log.append("agent_cycle_completed", details=summary)
        return summary
