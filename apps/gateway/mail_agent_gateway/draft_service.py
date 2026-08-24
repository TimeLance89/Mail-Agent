from __future__ import annotations

from typing import Any

from mail_agent_core.brain import AgentBrain
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, MailActionProposal, MailActionType
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.signature import stamp_outgoing_proposal, strip_agent_signature

from .audit import AuditLog
from .mail_store import MailStore
from .state import JsonStateStore


class DraftService:
    def __init__(
        self,
        *,
        mail_store: MailStore,
        identity_manager: IdentityManager,
        state_store: JsonStateStore,
        policy_engine: PolicyEngine,
        audit_log: AuditLog,
        brain: AgentBrain | None = None,
    ) -> None:
        self.mail_store = mail_store
        self.identity_manager = identity_manager
        self.state_store = state_store
        self.policy_engine = policy_engine
        self.audit_log = audit_log
        self.brain = brain

    def _profile(self) -> AgentProfile:
        state = self.state_store.read()
        config = state.get("configuration")
        if not state.get("onboarding_completed") or not isinstance(config, dict):
            raise RuntimeError("Onboarding is not complete")
        return AgentProfile.model_validate(config["profile"])

    def public_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        result = dict(draft)
        result["editable_body"] = strip_agent_signature(str(draft.get("body") or ""))
        return result

    def edit(
        self,
        draft_id: str,
        *,
        subject: str,
        body: str,
        recipient: str | None,
        actor: str,
    ) -> dict[str, Any]:
        draft = self.mail_store.get_draft(draft_id)
        proposal = MailActionProposal.model_validate(draft["proposal"])
        source = None
        if proposal.message_id:
            source = self.mail_store.get_message(proposal.mailbox_id, proposal.message_id)

        requested_recipient = (recipient or proposal.recipient or "").strip() or None
        original_action = str(proposal.metadata.get("drafted_from_action") or proposal.action.value)
        if original_action == MailActionType.SEND_REPLY.value or proposal.action == MailActionType.SEND_REPLY:
            if source is None:
                raise RuntimeError("Reply draft source message is missing")
            authoritative = str(source.get("sender") or "").strip()
            if requested_recipient and requested_recipient.casefold() != authoritative.casefold():
                raise RuntimeError("Reply recipient cannot differ from the original sender")
            requested_recipient = authoritative

        before_subject = str(proposal.subject or "")
        before_body = strip_agent_signature(str(proposal.body or ""))
        clean_body = strip_agent_signature(body)
        if not clean_body.strip():
            raise ValueError("Draft body cannot be empty")
        proposal.subject = subject.strip()
        proposal.body = clean_body
        proposal.recipient = requested_recipient

        profile = self._profile()
        identity = self.identity_manager.load()
        proposal = stamp_outgoing_proposal(
            proposal,
            identity,
            sign_payload=self.identity_manager.sign,
            user_signature=profile.email_signature,
        )
        updated = self.mail_store.update_draft(draft_id, proposal, actor=actor)

        feedback_recorded = False
        if self.brain is not None and (
            before_subject.strip() != subject.strip() or before_body.strip() != clean_body.strip()
        ):
            self.brain.ensure(identity, profile)
            feedback = self.brain.record_owner_edit(
                draft_id=draft_id,
                mailbox_id=proposal.mailbox_id,
                message_id=proposal.message_id,
                sender=str(source.get("sender") or "") if source else None,
                before_subject=before_subject,
                before_body=before_body,
                after_subject=subject.strip(),
                after_body=clean_body,
            )
            feedback_recorded = feedback is not None

        self.audit_log.append(
            "draft_edited_and_resigned",
            actor=actor,
            details={
                "draft_id": draft_id,
                "revision": updated.get("revision"),
                "agent_id": identity.agent_id,
                "owner_feedback_recorded": feedback_recorded,
            },
        )
        return self.public_draft(updated)

    def submit_for_approval(self, draft_id: str, *, actor: str) -> dict[str, Any]:
        draft = self.mail_store.get_draft(draft_id)
        if draft.get("approval_id"):
            approval = self.mail_store.get_approval(str(draft["approval_id"]))
            if approval["status"] == "pending":
                return {"draft": self.public_draft(draft), "approval": approval}
            raise RuntimeError("Draft already has a decided approval")

        proposal = MailActionProposal.model_validate(draft["proposal"])
        if not proposal.message_id:
            raise RuntimeError("Draft has no source message")
        source = self.mail_store.get_message(proposal.mailbox_id, proposal.message_id)
        if source is None:
            raise RuntimeError("Draft source message is missing")

        intended = str(proposal.metadata.get("drafted_from_action") or "")
        if intended == MailActionType.FORWARD.value:
            action = MailActionType.FORWARD
        elif intended == MailActionType.SEND_REPLY.value:
            action = MailActionType.SEND_REPLY
        else:
            sender = str(source.get("sender") or "").strip().casefold()
            recipient = str(proposal.recipient or "").strip().casefold()
            action = MailActionType.SEND_REPLY if sender and recipient == sender else MailActionType.FORWARD

        if action == MailActionType.SEND_REPLY:
            proposal.recipient = str(source.get("sender") or "").strip()
        elif not proposal.recipient:
            raise RuntimeError("Forward draft has no recipient")
        proposal.action = action

        profile = self._profile()
        identity = self.identity_manager.load()
        proposal = stamp_outgoing_proposal(
            proposal,
            identity,
            sign_payload=self.identity_manager.sign,
            user_signature=profile.email_signature,
        )
        decision = self.policy_engine.evaluate(profile, proposal)
        if not decision.allowed:
            raise RuntimeError(decision.reason)
        if not decision.requires_approval:
            raise RuntimeError("Outbound draft unexpectedly bypassed human approval")

        updated_draft = self.mail_store.update_draft(draft_id, proposal, actor=actor)
        approval = self.mail_store.enqueue_approval(proposal, decision)
        updated_draft = self.mail_store.link_draft_approval(
            draft_id,
            approval["approval_id"],
            source_action=action.value,
        )
        self.audit_log.append(
            "draft_submitted_for_approval",
            actor=actor,
            details={
                "draft_id": draft_id,
                "approval_id": approval["approval_id"],
                "action": action.value,
            },
        )
        return {"draft": self.public_draft(updated_draft), "approval": approval}
