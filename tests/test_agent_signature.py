from pathlib import Path

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, MailActionProposal, MailActionType, UsageType
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.signature import (
    assert_mandatory_agent_signature,
    enforce_agent_signature,
    stamp_outgoing_proposal,
)


def test_agent_signature_is_mandatory_and_idempotent(tmp_path: Path):
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="private")
    first = enforce_agent_signature("Hallo", identity, user_signature="Viele Grüße")
    second = enforce_agent_signature(first, identity, user_signature="Viele Grüße")
    assert first == second
    assert f"Agent-ID: {identity.agent_id}" in second
    assert f"Agent-Fingerprint: {identity.fingerprint}" in second
    assert_mandatory_agent_signature(second, identity)


def test_policy_rejects_unstamped_outgoing_mail(tmp_path: Path):
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="private")
    proposal = MailActionProposal(
        action=MailActionType.CREATE_DRAFT,
        mailbox_id="mb",
        message_id="m",
        recipient="person@example.com",
        subject="Hi",
        body="Hallo",
        confidence=0.9,
    )
    profile = AgentProfile(owner_id="owner", agent_name="Nova", usage_type=UsageType.PRIVATE)
    assert PolicyEngine().evaluate(profile, proposal).allowed is False
    stamped = stamp_outgoing_proposal(proposal, identity)
    assert PolicyEngine().evaluate(profile, stamped).allowed is True
