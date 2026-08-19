from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from mail_agent_core.activity import AgentActivityStore
from mail_agent_core.agent import MailAgent, MailMessageContext, ThreadMessageContext
from mail_agent_core.behavior import apply_rule_overrides, behavior_is_active, matching_rule
from mail_agent_core.brain import AgentBrain
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentBehaviorSettings,
    AgentExecutionMode,
    AgentProfile,
    MailActionProposal,
    MailActionType,
    RuleMode,
)
from mail_agent_core.shadow import ShadowReportStore
from mail_agent_core.signature import stamp_outgoing_proposal

from .action_executor import MailActionExecutor
from .agent_queue import AgentWorkQueue
from .audit import AuditLog
from .mail_store import MailStore
from .state import JsonStateStore

_REMOTE_MUTATIONS = {
    MailActionType.MARK_READ,
    MailActionType.MOVE,
    MailActionType.ARCHIVE,
}
_OUTBOUND_ACTIONS = {
    MailActionType.CREATE_DRAFT,
    MailActionType.SEND_REPLY,
    MailActionType.FORWARD,
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
        brain: AgentBrain | None = None,
        activity: AgentActivityStore | None = None,
        shadow_reports: ShadowReportStore | None = None,
    ):
        self.mail_agent = mail_agent
        self.identity_manager = identity_manager
        self.mail_store = mail_store
        self.state_store = state_store
        self.providers = providers
        self.audit_log = audit_log
        self.action_executor = action_executor
        self.brain = brain or AgentBrain(mail_store.path.parent / "brain")
        self.activity = activity or AgentActivityStore(mail_store.path.parent / "agent-activity.jsonl")
        self.shadow_reports = shadow_reports or ShadowReportStore(
            mail_store.path.parent / "shadow-reports.jsonl"
        )
        self.work_queue = AgentWorkQueue(mail_store)
        self.shadow_queue = AgentWorkQueue(
            mail_store,
            processing_table="agent_shadow_processing",
        )

    def _configuration(self) -> dict[str, Any]:
        state = self.state_store.read()
        config = state.get("configuration")
        if not state.get("onboarding_completed") or not isinstance(config, dict):
            raise RuntimeError("Onboarding is not complete")
        return config

    @staticmethod
    def behavior(config: dict[str, Any]) -> AgentBehaviorSettings:
        return AgentBehaviorSettings.model_validate(config.get("behavior") or {})

    def _ensure_brain(self, config: dict[str, Any]) -> tuple[Any, AgentProfile]:
        identity = self.identity_manager.load()
        profile = AgentProfile.model_validate(config["profile"])
        self.brain.ensure(identity, profile)
        return identity, profile

    def mailbox_status(self, mailbox_id: str) -> dict[str, Any]:
        config = self._configuration()
        behavior = self.behavior(config)
        self._ensure_brain(config)
        live_pending = self.work_queue.pending_count(mailbox_id)
        shadow_pending = self.shadow_queue.pending_count(mailbox_id)
        pending = (
            shadow_pending
            if behavior.execution_mode == AgentExecutionMode.SHADOW
            else live_pending
        )
        return {
            "mailbox_id": mailbox_id,
            "pending": pending,
            "live_pending": live_pending,
            "shadow_pending": shadow_pending,
            "execution_mode": behavior.execution_mode.value,
            "enabled": behavior.enabled,
            "auto_analyze_new_mail": behavior.auto_analyze_new_mail,
            "schedule_active": behavior_is_active(behavior),
            "max_messages_per_cycle": behavior.max_messages_per_cycle,
            "provider": str(config.get("provider") or ""),
            "model": str(config.get("model") or ""),
        }

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
                message_id=str(
                    item.get("remote_id") or item.get("internet_message_id") or item.get("uid")
                ),
                sender=str(item.get("sender") or ""),
                recipients=list(item.get("recipients") or []),
                subject=str(item.get("subject") or ""),
                body=str(item.get("body_text") or ""),
                sent_at=item.get("sent_at"),
            )
            for item in stored
        ]
        return message.model_copy(update={"thread_context": context})

    @staticmethod
    def _planned_artifacts(
        *,
        proposal: MailActionProposal,
        behavior: AgentBehaviorSettings,
        confidence_ok: bool,
        artifacts_allowed: bool,
        policy_allowed: bool,
        requires_approval: bool,
    ) -> list[str]:
        if not confidence_ok or not artifacts_allowed or not policy_allowed:
            return []
        planned: list[str] = []
        if requires_approval:
            planned.append("approval")
        elif proposal.action in _REMOTE_MUTATIONS:
            planned.append("execution")
        if (
            behavior.auto_create_drafts
            and proposal.body
            and proposal.action in _OUTBOUND_ACTIONS
        ):
            planned.append("draft")
        return planned

    @staticmethod
    def _simulated_outcome(
        *,
        rule_mode: RuleMode,
        confidence_ok: bool,
        policy_allowed: bool,
        planned_artifacts: list[str],
    ) -> str:
        if rule_mode == RuleMode.IGNORE:
            return "ignored"
        if not confidence_ok:
            return "below_confidence"
        if not policy_allowed:
            return "blocked"
        if "approval" in planned_artifacts:
            return "would_approval"
        if "execution" in planned_artifacts:
            return "would_execute"
        if "draft" in planned_artifacts:
            return "would_draft"
        return "no_action"

    @staticmethod
    def _artifact_detail(
        *,
        simulation: bool,
        create_artifacts: bool,
        artifacts_allowed: bool,
        confidence_ok: bool,
        confidence: float,
        threshold: float,
        policy_allowed: bool,
        policy_reason: str,
        planned_artifacts: list[str],
        approval: dict[str, Any] | None,
        draft: dict[str, Any] | None,
        execution: dict[str, Any] | None,
    ) -> str:
        if not artifacts_allowed:
            return "Die aktive Regel erlaubt Analyse, aber keine weitere Mail-Aktion."
        if not confidence_ok:
            return f"Konfidenz {confidence:.2f} liegt unter der Schwelle {threshold:.2f}."
        if not policy_allowed:
            return f"Policy Engine blockiert die Aktion: {policy_reason}"
        if simulation:
            if planned_artifacts:
                labels = {
                    "approval": "Freigabe anfordern",
                    "draft": "Entwurf erstellen",
                    "execution": "Mailbox-Aktion ausführen",
                }
                planned = ", ".join(labels.get(item, item) for item in planned_artifacts)
                return f"Shadow Mode: würde {planned}. Es wurde nichts verändert."
            return "Shadow Mode: keine Aktion erforderlich. Es wurde nichts verändert."
        if not create_artifacts:
            return "Analyse ohne Erzeugung oder Ausführung von Mail-Artefakten."
        parts = []
        if draft:
            parts.append("signierter Entwurf erstellt")
        if approval:
            parts.append("menschliche Freigabe angefordert")
        if execution:
            parts.append("erlaubte Mailbox-Aktion ausgeführt")
        return " · ".join(parts) if parts else "Keine weitere Aktion erforderlich."

    async def analyze_message(
        self,
        message: MailMessageContext,
        *,
        create_artifacts: bool = True,
        minimum_confidence: float | None = None,
        trace_id: str | None = None,
        trace_trigger: str = "manual",
        simulation: bool = False,
        shadow_run_id: str | None = None,
    ) -> dict[str, Any]:
        config = self._configuration()
        provider_name = str(config["provider"])
        provider = self.providers.get(provider_name)
        if provider is None:
            raise RuntimeError("Configured provider is unavailable")
        identity, profile = self._ensure_brain(config)
        behavior = self.behavior(config)
        threshold = behavior.minimum_confidence if minimum_confidence is None else minimum_confidence
        message = self._with_thread_context(message, behavior)
        model = str(config["model"])

        if trace_id is None:
            trace_id = self.activity.begin_message(
                mailbox_id=message.mailbox_id,
                message_id=message.message_id,
                thread_id=message.thread_id,
                sender=message.sender,
                subject=message.subject,
                provider=provider_name,
                model=model,
                trigger=trace_trigger,
            )

        try:
            self.activity.record(
                trace_id=trace_id,
                stage="context",
                status="completed",
                detail=(
                    f"{len(message.thread_context)} frühere Thread-Nachrichten als Kontext geladen."
                ),
                data={
                    "thread_context_messages": len(message.thread_context),
                    "execution_mode": "shadow" if simulation else "live",
                    "shadow_run_id": shadow_run_id,
                },
            )
            brain_context = self.brain.build_context(message)
            self.activity.record(
                trace_id=trace_id,
                stage="brain",
                status="completed",
                detail="SOUL, Besitzer-Memory und Sender-Memory als beratenden Kontext geladen.",
                data={"brain_chars": len(brain_context)},
            )

            llm_started = time.perf_counter()
            try:
                analysis = await self.mail_agent.analyze(
                    profile=profile,
                    provider=provider,
                    model=model,
                    message=message,
                    identity=identity,
                    sign_payload=self.identity_manager.sign,
                    brain_context=brain_context,
                )
            except Exception as exc:
                self.activity.record(
                    trace_id=trace_id,
                    stage="llm",
                    status="failed",
                    detail=str(exc),
                    duration_ms=round((time.perf_counter() - llm_started) * 1000),
                    data={"provider": provider_name, "model": model},
                )
                raise

            self.activity.record(
                trace_id=trace_id,
                stage="llm",
                status="completed",
                detail=f"{provider_name} / {model} hat die Mail analysiert.",
                duration_ms=round((time.perf_counter() - llm_started) * 1000),
                data={"provider": provider_name, "model": model},
            )

            original_action = analysis.proposal.action.value
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

            self.activity.record(
                trace_id=trace_id,
                stage="proposal",
                status="completed",
                detail=(
                    analysis.proposal.reason
                    or analysis.proposal.summary
                    or "LLM-Vorschlag erzeugt."
                ),
                data={
                    "action": analysis.proposal.action.value,
                    "original_action": original_action,
                    "category": analysis.proposal.category.value,
                    "priority": analysis.proposal.priority.value,
                    "confidence": analysis.proposal.confidence,
                    "needs_reply": analysis.proposal.needs_reply,
                    "rule_mode": rule_mode.value,
                },
            )
            self.activity.record(
                trace_id=trace_id,
                stage="policy",
                status="completed" if analysis.policy.allowed else "blocked",
                detail=analysis.policy.reason,
                data={
                    "allowed": analysis.policy.allowed,
                    "requires_approval": analysis.policy.requires_approval,
                    "risk": analysis.policy.risk,
                },
            )

            # Shadow Mode is deliberately read-only with respect to production intelligence and Brain.
            # It may read SOUL/MEMORY as context, but simulation results never become learned history.
            if not simulation:
                self.mail_store.update_message_intelligence(
                    message.mailbox_id,
                    message.message_id,
                    priority=analysis.proposal.priority.value,
                    category=analysis.proposal.category.value,
                    summary=analysis.proposal.summary,
                    needs_reply=analysis.proposal.needs_reply,
                )
                self.brain.record_analysis(
                    message=message,
                    proposal=analysis.proposal,
                    policy=analysis.policy,
                )

            approval = None
            draft = None
            execution = None
            confidence_ok = analysis.proposal.confidence >= threshold
            artifacts_allowed = rule_mode not in {RuleMode.ANALYZE_ONLY, RuleMode.IGNORE}
            planned_artifacts = self._planned_artifacts(
                proposal=analysis.proposal,
                behavior=behavior,
                confidence_ok=confidence_ok,
                artifacts_allowed=artifacts_allowed,
                policy_allowed=analysis.policy.allowed,
                requires_approval=analysis.policy.requires_approval,
            )

            if (
                not simulation
                and create_artifacts
                and artifacts_allowed
                and confidence_ok
                and analysis.policy.allowed
            ):
                if analysis.policy.requires_approval:
                    approval = self.mail_store.enqueue_approval(analysis.proposal, analysis.policy)
                elif analysis.proposal.action in _REMOTE_MUTATIONS:
                    if self.action_executor is None:
                        raise RuntimeError("Remote action executor is not configured")
                    execution = await self.action_executor.execute_direct(analysis.proposal)
                if (
                    behavior.auto_create_drafts
                    and analysis.proposal.body
                    and analysis.proposal.action in _OUTBOUND_ACTIONS
                ):
                    draft = self.mail_store.create_draft(
                        analysis.proposal,
                        approval_id=approval["approval_id"] if approval else None,
                    )

            artifact_detail = self._artifact_detail(
                simulation=simulation,
                create_artifacts=create_artifacts,
                artifacts_allowed=artifacts_allowed,
                confidence_ok=confidence_ok,
                confidence=analysis.proposal.confidence,
                threshold=threshold,
                policy_allowed=analysis.policy.allowed,
                policy_reason=analysis.policy.reason,
                planned_artifacts=planned_artifacts,
                approval=approval,
                draft=draft,
                execution=execution,
            )
            self.activity.record(
                trace_id=trace_id,
                stage="artifact",
                status="completed",
                detail=artifact_detail,
                data={
                    "artifact": (
                        "draft"
                        if draft
                        else "approval"
                        if approval
                        else "execution"
                        if execution
                        else "none"
                    ),
                    "approval_id": approval.get("approval_id") if approval else None,
                    "draft_id": draft.get("draft_id") if draft else None,
                    "execution_status": execution.get("execution_status") if execution else None,
                    "confidence_threshold": threshold,
                    "execution_mode": "shadow" if simulation else "live",
                    "planned_artifacts": planned_artifacts,
                    "side_effects": 0 if simulation else int(bool(approval or draft or execution)),
                    "shadow_run_id": shadow_run_id,
                },
            )

            simulated_outcome = self._simulated_outcome(
                rule_mode=rule_mode,
                confidence_ok=confidence_ok,
                policy_allowed=analysis.policy.allowed,
                planned_artifacts=planned_artifacts,
            )
            if simulation:
                outcome = f"shadow_{simulated_outcome}"
                reason = artifact_detail
            elif not confidence_ok:
                outcome = "below_confidence"
                reason = artifact_detail
            elif not analysis.policy.allowed:
                outcome = "blocked"
                reason = analysis.policy.reason
            elif approval:
                outcome = "approval_required"
                reason = "Die Aktion wartet auf menschliche Freigabe."
            elif execution:
                outcome = "executed"
                reason = "Die Policy erlaubte die Mailbox-Aktion ohne zusätzliche Freigabe."
            elif draft:
                outcome = "draft_created"
                reason = "Ein signierter Entwurf wurde vorbereitet."
            else:
                outcome = "no_action"
                reason = artifact_detail
            self.activity.finish(trace_id, outcome=outcome, reason=reason)

            payload = analysis.model_dump(mode="json")
            payload["approval"] = approval
            payload["draft"] = draft
            payload["execution"] = execution
            payload["confidence_threshold"] = threshold
            payload["confidence_accepted"] = confidence_ok
            payload["rule_mode"] = rule_mode.value
            payload["brain"] = self.brain.public_status()
            payload["trace_id"] = trace_id
            payload["simulation"] = simulation
            payload["planned_artifacts"] = planned_artifacts
            payload["simulated_outcome"] = simulated_outcome
            payload["side_effects"] = 0 if simulation else int(bool(approval or draft or execution))
            return payload
        except Exception as exc:
            self.activity.finish(trace_id, outcome="error", reason=str(exc))
            raise

    @staticmethod
    def _message_context(item: dict[str, Any], mailbox_id: str) -> MailMessageContext:
        message_id = str(
            item.get("remote_id") or item.get("internet_message_id") or item.get("uid")
        )
        return MailMessageContext(
            mailbox_id=mailbox_id,
            message_id=message_id,
            thread_id=str(item.get("thread_key") or "") or None,
            sender=str(item.get("sender") or ""),
            recipients=list(item.get("recipients") or []),
            subject=str(item.get("subject") or ""),
            body=str(item.get("body_text") or ""),
            sent_at=item.get("sent_at"),
        )

    async def _simulate_item(
        self,
        item: dict[str, Any],
        *,
        mailbox_id: str,
        trigger: str,
        run_id: str,
    ) -> dict[str, Any]:
        config = self._configuration()
        behavior = self.behavior(config)
        provider_name = str(config.get("provider") or "")
        model = str(config.get("model") or "")
        context = self._message_context(item, mailbox_id)
        rule = matching_rule(context.sender, behavior)
        if rule is not None and rule.mode == RuleMode.IGNORE:
            trace_id = self.activity.begin_message(
                mailbox_id=mailbox_id,
                message_id=context.message_id,
                thread_id=context.thread_id,
                sender=context.sender,
                subject=context.subject,
                provider=provider_name,
                model=model,
                trigger=trigger,
            )
            self.activity.record(
                trace_id=trace_id,
                stage="rule",
                status="completed",
                detail=f"Regel {rule.pattern!r} würde diese Mail ignorieren.",
                data={
                    "rule_mode": rule.mode.value,
                    "execution_mode": "shadow",
                    "matched_rule": rule.pattern,
                    "shadow_run_id": run_id,
                    "side_effects": 0,
                },
            )
            self.activity.finish(
                trace_id,
                outcome="shadow_ignored",
                reason="Shadow Mode: Besitzerregel würde die Mail vor der LLM-Analyse ignorieren.",
            )
            return {
                "message_id": context.message_id,
                "thread_id": context.thread_id,
                "sender": context.sender,
                "subject": context.subject,
                "action": "none",
                "original_action": "none",
                "category": rule.category.value if rule.category else "other",
                "priority": rule.priority.value if rule.priority else "normal",
                "confidence": 1.0,
                "needs_reply": False,
                "rule_mode": rule.mode.value,
                "matched_rule": rule.pattern,
                "policy_allowed": False,
                "requires_approval": False,
                "risk": "none",
                "planned_artifacts": [],
                "simulated_outcome": "ignored",
                "reason": "Besitzerregel würde die Mail ignorieren.",
                "trace_id": trace_id,
            }

        result = await self.analyze_message(
            context,
            create_artifacts=True,
            trace_trigger=trigger,
            simulation=True,
            shadow_run_id=run_id,
        )
        proposal = result["proposal"]
        policy = result["policy"]
        return {
            "message_id": context.message_id,
            "thread_id": context.thread_id,
            "sender": context.sender,
            "subject": context.subject,
            "action": proposal.get("action"),
            "original_action": (proposal.get("metadata") or {}).get(
                "drafted_from_action",
                proposal.get("action"),
            ),
            "category": proposal.get("category"),
            "priority": proposal.get("priority"),
            "confidence": proposal.get("confidence"),
            "needs_reply": proposal.get("needs_reply"),
            "rule_mode": result.get("rule_mode"),
            "matched_rule": rule.pattern if rule else None,
            "policy_allowed": policy.get("allowed"),
            "requires_approval": policy.get("requires_approval"),
            "risk": policy.get("risk"),
            "planned_artifacts": result.get("planned_artifacts") or [],
            "simulated_outcome": result.get("simulated_outcome"),
            "reason": proposal.get("reason") or policy.get("reason") or "",
            "trace_id": result.get("trace_id"),
        }

    async def shadow_replay(
        self,
        mailbox_id: str,
        *,
        limit: int = 25,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 500))
        items = self.mail_store.list_messages(mailbox_id, limit)
        run_id = "shadow_" + uuid.uuid4().hex
        started_at = _utc_now()
        results: list[dict[str, Any]] = []
        total = len(items)
        for index, item in enumerate(items, start=1):
            try:
                result = await self._simulate_item(
                    item,
                    mailbox_id=mailbox_id,
                    trigger="shadow_replay",
                    run_id=run_id,
                )
            except Exception as exc:
                context = self._message_context(item, mailbox_id)
                result = {
                    "message_id": context.message_id,
                    "thread_id": context.thread_id,
                    "sender": context.sender,
                    "subject": context.subject,
                    "simulated_outcome": "error",
                    "error": str(exc),
                    "reason": "Shadow-Analyse fehlgeschlagen.",
                }
            results.append(result)
            if progress:
                progress(index, total)

        report = self.shadow_reports.save_report(
            run_id=run_id,
            mailbox_id=mailbox_id,
            requested=limit,
            results=results,
            started_at=started_at,
            finished_at=_utc_now(),
            trigger="historical_replay",
        )
        self.audit_log.append(
            "agent_shadow_replay_completed",
            details={
                "run_id": run_id,
                "mailbox_id": mailbox_id,
                "requested": limit,
                "analyzed": report["analyzed"],
                "errors": report["errors"],
                "side_effects": 0,
            },
        )
        return report

    def simulate_rule(
        self,
        *,
        sender: str,
        action: MailActionType,
        confidence: float,
        priority: Any,
        category: Any,
        needs_reply: bool,
    ) -> dict[str, Any]:
        config = self._configuration()
        identity, profile = self._ensure_brain(config)
        behavior = self.behavior(config)
        matched = matching_rule(sender, behavior)
        rule_mode, final_priority, final_category = apply_rule_overrides(
            sender=sender,
            settings=behavior,
            priority=priority,
            category=category,
        )
        original_action = action
        final_action = action
        if rule_mode == RuleMode.DRAFT_ONLY and action in {
            MailActionType.SEND_REPLY,
            MailActionType.FORWARD,
        }:
            final_action = MailActionType.CREATE_DRAFT

        proposal = MailActionProposal(
            action=final_action,
            mailbox_id="rule-simulator",
            message_id="rule-simulator",
            recipient=sender if final_action in _OUTBOUND_ACTIONS else None,
            subject="Rule simulation",
            body="Simulierter Entwurf" if final_action in _OUTBOUND_ACTIONS else None,
            confidence=confidence,
            reason="Deterministische Regelsimulation",
            priority=final_priority,
            category=final_category,
            needs_reply=needs_reply,
        )
        proposal = stamp_outgoing_proposal(
            proposal,
            identity,
            sign_payload=self.identity_manager.sign,
            user_signature=profile.email_signature,
        )
        policy = self.mail_agent.policy_engine.evaluate(profile, proposal)
        confidence_ok = proposal.confidence >= behavior.minimum_confidence
        artifacts_allowed = rule_mode not in {RuleMode.ANALYZE_ONLY, RuleMode.IGNORE}
        planned = self._planned_artifacts(
            proposal=proposal,
            behavior=behavior,
            confidence_ok=confidence_ok,
            artifacts_allowed=artifacts_allowed,
            policy_allowed=policy.allowed,
            requires_approval=policy.requires_approval,
        )
        outcome = self._simulated_outcome(
            rule_mode=rule_mode,
            confidence_ok=confidence_ok,
            policy_allowed=policy.allowed,
            planned_artifacts=planned,
        )
        return {
            "shadow": True,
            "side_effects": 0,
            "sender": sender,
            "matched_rule": matched.model_dump(mode="json") if matched else None,
            "rule_mode": rule_mode.value,
            "original_action": original_action.value,
            "resulting_action": proposal.action.value,
            "priority": proposal.priority.value,
            "category": proposal.category.value,
            "confidence": proposal.confidence,
            "confidence_threshold": behavior.minimum_confidence,
            "confidence_accepted": confidence_ok,
            "policy": policy.model_dump(mode="json"),
            "planned_artifacts": planned,
            "simulated_outcome": outcome,
        }

    async def _run_shadow_mailbox(
        self,
        mailbox_id: str,
        *,
        behavior: AgentBehaviorSettings,
    ) -> dict[str, Any]:
        pending_before = self.shadow_queue.pending_count(mailbox_id)
        messages = self.shadow_queue.list_pending(mailbox_id, behavior.max_messages_per_cycle)
        run_id = "shadow_" + uuid.uuid4().hex
        started_at = _utc_now()
        results: list[dict[str, Any]] = []
        errors = 0
        for item in messages:
            context = self._message_context(item, mailbox_id)
            try:
                result = await self._simulate_item(
                    item,
                    mailbox_id=mailbox_id,
                    trigger="shadow_cycle",
                    run_id=run_id,
                )
                self.mail_store.record_shadow_processing(
                    mailbox_id,
                    context.message_id,
                    status="processed",
                    proposal_action=result.get("action"),
                    confidence=result.get("confidence"),
                )
            except Exception as exc:
                errors += 1
                result = {
                    "message_id": context.message_id,
                    "thread_id": context.thread_id,
                    "sender": context.sender,
                    "subject": context.subject,
                    "simulated_outcome": "error",
                    "error": str(exc),
                    "reason": "Shadow-Analyse fehlgeschlagen.",
                }
                self.mail_store.record_shadow_processing(
                    mailbox_id,
                    context.message_id,
                    status="error",
                    error=str(exc),
                )
            results.append(result)

        report = self.shadow_reports.save_report(
            run_id=run_id,
            mailbox_id=mailbox_id,
            requested=len(messages),
            results=results,
            started_at=started_at,
            finished_at=_utc_now(),
            trigger="automatic_cycle",
        )
        pending_after = self.shadow_queue.pending_count(mailbox_id)
        outcomes = report.get("outcomes") or {}
        summary = {
            "mailbox_id": mailbox_id,
            "execution_mode": "shadow",
            "processed": len(messages) - errors,
            "ignored": int(outcomes.get("ignored") or 0),
            "urgent": sum(1 for item in results if item.get("priority") == "urgent"),
            "drafts": 0,
            "approvals": 0,
            "executed": 0,
            "would_draft": int(outcomes.get("would_draft") or 0),
            "would_approval": int(outcomes.get("would_approval") or 0),
            "would_execute": int(outcomes.get("would_execute") or 0),
            "below_confidence": int(outcomes.get("below_confidence") or 0),
            "errors": errors,
            "side_effects": 0,
            "shadow_run_id": run_id,
            "pending_before": pending_before,
            "pending_after": pending_after,
            "brain": self.brain.public_status(),
            "activity": self.activity.summary(mailbox_id=mailbox_id),
        }
        self.audit_log.append("agent_shadow_cycle_completed", details=summary)
        return summary

    async def run_mailbox(self, mailbox_id: str, *, force: bool = False) -> dict[str, Any]:
        config = self._configuration()
        behavior = self.behavior(config)
        self._ensure_brain(config)
        queue = (
            self.shadow_queue
            if behavior.execution_mode == AgentExecutionMode.SHADOW
            else self.work_queue
        )
        pending_before = queue.pending_count(mailbox_id)

        if not force and (not behavior.enabled or not behavior.auto_analyze_new_mail):
            summary = {
                "mailbox_id": mailbox_id,
                "execution_mode": behavior.execution_mode.value,
                "processed": 0,
                "skipped": "agent_disabled",
                "pending_before": pending_before,
                "pending_after": pending_before,
            }
            if behavior.execution_mode == AgentExecutionMode.LIVE:
                self.brain.record_cycle(summary)
            summary["brain"] = self.brain.public_status()
            return summary
        if not force and not behavior_is_active(behavior):
            summary = {
                "mailbox_id": mailbox_id,
                "execution_mode": behavior.execution_mode.value,
                "processed": 0,
                "skipped": "outside_schedule",
                "pending_before": pending_before,
                "pending_after": pending_before,
            }
            if behavior.execution_mode == AgentExecutionMode.LIVE:
                self.brain.record_cycle(summary)
            summary["brain"] = self.brain.public_status()
            return summary

        if behavior.execution_mode == AgentExecutionMode.SHADOW:
            return await self._run_shadow_mailbox(mailbox_id, behavior=behavior)

        messages = self.work_queue.list_pending(mailbox_id, behavior.max_messages_per_cycle)
        processed = 0
        ignored = 0
        urgent = 0
        drafts = 0
        approvals = 0
        executed = 0
        below_confidence = 0
        errors = 0
        provider_name = str(config.get("provider") or "")
        model = str(config.get("model") or "")
        for item in messages:
            context = self._message_context(item, mailbox_id)
            rule = matching_rule(context.sender, behavior)
            if rule is not None and rule.mode == RuleMode.IGNORE:
                trace_id = self.activity.begin_message(
                    mailbox_id=mailbox_id,
                    message_id=context.message_id,
                    thread_id=context.thread_id,
                    sender=context.sender,
                    subject=context.subject,
                    provider=provider_name,
                    model=model,
                    trigger="cycle",
                )
                self.activity.record(
                    trace_id=trace_id,
                    stage="rule",
                    status="completed",
                    detail=f"Deterministische Regel {rule.pattern!r} setzt diese Mail auf Ignorieren.",
                    data={"rule_mode": rule.mode.value, "execution_mode": "live"},
                )
                self.activity.finish(
                    trace_id,
                    outcome="ignored",
                    reason="Eine Besitzerregel hat die Mail vor der LLM-Analyse ausgeschlossen.",
                )
                self.mail_store.record_agent_processing(
                    mailbox_id,
                    context.message_id,
                    status="ignored_rule",
                )
                ignored += 1
                continue
            try:
                result = await self.analyze_message(
                    context,
                    create_artifacts=True,
                    trace_trigger="cycle",
                )
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
                    context.message_id,
                    status=status,
                    proposal_action=proposal.get("action"),
                    confidence=float(proposal.get("confidence") or 0.0),
                )
                processed += 1
            except Exception as exc:
                errors += 1
                self.mail_store.record_agent_processing(
                    mailbox_id,
                    context.message_id,
                    status="error",
                    error=str(exc),
                )
                self.audit_log.append(
                    "agent_message_failed",
                    details={
                        "mailbox_id": mailbox_id,
                        "message_id": context.message_id,
                        "error": str(exc),
                    },
                )

        pending_after = self.work_queue.pending_count(mailbox_id)
        summary = {
            "mailbox_id": mailbox_id,
            "execution_mode": "live",
            "processed": processed,
            "ignored": ignored,
            "urgent": urgent,
            "drafts": drafts,
            "approvals": approvals,
            "executed": executed,
            "below_confidence": below_confidence,
            "errors": errors,
            "pending_before": pending_before,
            "pending_after": pending_after,
        }
        self.brain.record_cycle(summary)
        summary["brain"] = self.brain.public_status()
        summary["activity"] = self.activity.summary(mailbox_id=mailbox_id)
        self.audit_log.append("agent_cycle_completed", details=summary)
        return summary
