import pytest

from mail_agent_core.models import (
    AgentProfile,
    AutonomyMode,
    MailActionProposal,
    MailActionType,
    UsageType,
)
from mail_agent_core.policy import PolicyEngine


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine()


def profile(mode: AutonomyMode, usage: UsageType = UsageType.PRIVATE) -> AgentProfile:
    return AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=usage,
        autonomy_mode=mode,
    )


def proposal(action: MailActionType) -> MailActionProposal:
    metadata = {}
    if action in {MailActionType.CREATE_DRAFT, MailActionType.SEND_REPLY, MailActionType.FORWARD}:
        metadata = {
            "agent_signature_required": True,
            "agent_id": "ma_test",
            "agent_fingerprint": "f" * 64,
            "agent_signature_algorithm": "ed25519",
            "agent_message_signature": "signed-message",
        }
    return MailActionProposal(action=action, mailbox_id="mailbox-1", metadata=metadata)


def test_observer_can_read_but_not_draft(engine: PolicyEngine):
    assert engine.evaluate(profile(AutonomyMode.OBSERVER), proposal(MailActionType.READ)).allowed
    decision = engine.evaluate(profile(AutonomyMode.OBSERVER), proposal(MailActionType.CREATE_DRAFT))
    assert not decision.allowed


def test_assistant_can_propose_send_but_it_always_requires_approval(engine: PolicyEngine):
    decision = engine.evaluate(profile(AutonomyMode.ASSISTANT), proposal(MailActionType.SEND_REPLY))
    assert decision.allowed
    assert decision.requires_approval
    assert decision.risk == "high"


def test_copilot_requires_approval_to_send(engine: PolicyEngine):
    decision = engine.evaluate(profile(AutonomyMode.COPILOT), proposal(MailActionType.SEND_REPLY))
    assert decision.allowed
    assert decision.requires_approval
    assert decision.risk == "high"


def test_autonomous_still_requires_approval_for_high_impact_v01(engine: PolicyEngine):
    decision = engine.evaluate(profile(AutonomyMode.AUTONOMOUS), proposal(MailActionType.DELETE))
    assert decision.allowed
    assert decision.requires_approval


def test_work_mutation_is_more_conservative(engine: PolicyEngine):
    decision = engine.evaluate(
        profile(AutonomyMode.COPILOT, UsageType.WORK),
        proposal(MailActionType.ARCHIVE),
    )
    assert decision.allowed
    assert decision.requires_approval
