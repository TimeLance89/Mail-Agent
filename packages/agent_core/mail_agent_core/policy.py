from __future__ import annotations

from .models import AgentProfile, AutonomyMode, MailActionProposal, MailActionType, PolicyDecision, UsageType


class PolicyEngine:
    """Code-level enforcement boundary between model proposals and mailbox execution."""

    _READ_ONLY = {
        MailActionType.READ,
        MailActionType.SUMMARIZE,
        MailActionType.CLASSIFY,
    }
    _LOW_IMPACT = {
        MailActionType.CREATE_DRAFT,
        MailActionType.MARK_READ,
    }
    _MUTATING = {
        MailActionType.MOVE,
        MailActionType.ARCHIVE,
    }
    _HIGH_IMPACT = {
        MailActionType.DELETE,
        MailActionType.SEND_REPLY,
        MailActionType.FORWARD,
    }

    def evaluate(self, profile: AgentProfile, proposal: MailActionProposal) -> PolicyDecision:
        action = proposal.action

        if action in {
            MailActionType.CREATE_DRAFT,
            MailActionType.SEND_REPLY,
            MailActionType.FORWARD,
        }:
            if (
                proposal.metadata.get("agent_signature_required") is not True
                or not proposal.metadata.get("agent_id")
                or not proposal.metadata.get("agent_fingerprint")
                or proposal.metadata.get("agent_signature_algorithm") != "ed25519"
                or not proposal.metadata.get("agent_message_signature")
            ):
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    risk="high",
                    reason="Outbound agent mail without mandatory signed Agent-ID is forbidden",
                )

        if action in self._READ_ONLY:
            return PolicyDecision(allowed=True, requires_approval=False, risk="low", reason="Read-only action")

        if profile.autonomy_mode == AutonomyMode.OBSERVER:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                risk="medium",
                reason="Observer mode forbids mailbox modifications and drafts",
            )

        if action in self._LOW_IMPACT:
            return PolicyDecision(allowed=True, requires_approval=False, risk="low", reason="Low-impact action")

        if profile.autonomy_mode == AutonomyMode.ASSISTANT:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                risk="medium",
                reason="Assistant mode may propose but not execute mailbox mutations",
            )

        if action in self._MUTATING:
            if profile.usage_type in {UsageType.WORK, UsageType.BUSINESS}:
                return PolicyDecision(
                    allowed=True,
                    requires_approval=profile.autonomy_mode != AutonomyMode.AUTONOMOUS,
                    risk="medium",
                    reason="Work/business mailbox mutation is approval-sensitive",
                )
            return PolicyDecision(
                allowed=True,
                requires_approval=profile.autonomy_mode == AutonomyMode.COPILOT,
                risk="medium",
                reason="Mailbox mutation follows autonomy setting",
            )

        if action in self._HIGH_IMPACT:
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                risk="high",
                reason="Sending, forwarding, and deletion require human approval",
            )

        return PolicyDecision(allowed=False, requires_approval=False, risk="high", reason="Unknown action")
