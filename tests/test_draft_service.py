from __future__ import annotations

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentProfile,
    AutonomyMode,
    MailActionProposal,
    MailActionType,
    UsageType,
)
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.signature import assert_mandatory_agent_signature, stamp_outgoing_proposal
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.draft_service import DraftService
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


def make_service(tmp_path):
    store = MailStore(tmp_path / "mail.db")
    identity = IdentityManager(tmp_path / "identity")
    created_identity = identity.create(owner_id="owner", agent_name="Nova", usage_type="work")
    state = JsonStateStore(tmp_path / "state.json")
    profile = AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.WORK,
        autonomy_mode=AutonomyMode.COPILOT,
        email_signature="Viele Grüße",
    )
    state.write(
        {
            "onboarding_completed": True,
            "configuration": {
                "profile": profile.model_dump(mode="json"),
                "provider": "fake",
                "model": "fake",
            },
        }
    )
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<source@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Question",
                sent_at=None,
                body_text="Can you answer?",
                seen=False,
            )
        ]
    )
    service = DraftService(
        mail_store=store,
        identity_manager=identity,
        state_store=state,
        policy_engine=PolicyEngine(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    return service, store, identity, created_identity


def create_reply_draft(store, manager, identity, *, approval=False):
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY if approval else MailActionType.CREATE_DRAFT,
        mailbox_id="mb",
        message_id="1",
        thread_id="thread",
        recipient="person@example.test",
        subject="Re: Question",
        body="Original answer",
        confidence=0.95,
        metadata={"drafted_from_action": "send_reply"},
    )
    proposal = stamp_outgoing_proposal(proposal, identity, sign_payload=manager.sign, user_signature="Viele Grüße")
    approval_id = None
    if approval:
        decision = PolicyEngine().evaluate(
            AgentProfile(
                owner_id="owner",
                agent_name="Nova",
                usage_type=UsageType.WORK,
                autonomy_mode=AutonomyMode.COPILOT,
            ),
            proposal,
        )
        queued = store.enqueue_approval(proposal, decision)
        approval_id = queued["approval_id"]
    return store.create_draft(proposal, approval_id=approval_id)


def test_edit_rebuilds_mandatory_signature_and_revision(tmp_path):
    service, store, manager, identity = make_service(tmp_path)
    draft = create_reply_draft(store, manager, identity)

    updated = service.edit(
        draft["draft_id"],
        subject="Re: Question",
        body="Changed by human",
        recipient="person@example.test",
        actor="local-user",
    )

    assert updated["revision"] == 2
    assert updated["edited_by"] == "local-user"
    assert updated["editable_body"].startswith("Changed by human")
    assert "[MAIL-AGENT-IDENTITY]" not in updated["editable_body"]
    assert_mandatory_agent_signature(updated["body"], identity)


def test_reply_recipient_cannot_be_changed_by_editor(tmp_path):
    service, store, manager, identity = make_service(tmp_path)
    draft = create_reply_draft(store, manager, identity)
    try:
        service.edit(
            draft["draft_id"],
            subject="Re: Question",
            body="Changed",
            recipient="attacker@example.test",
            actor="local-user",
        )
    except RuntimeError as exc:
        assert "recipient" in str(exc).lower()
    else:
        raise AssertionError("reply recipient was allowed to change")


def test_edit_updates_pending_approval_and_rejection_returns_draft_to_editable(tmp_path):
    service, store, manager, identity = make_service(tmp_path)
    draft = create_reply_draft(store, manager, identity, approval=True)
    approval_id = draft["approval_id"]

    updated = service.edit(
        draft["draft_id"],
        subject="Re: Question updated",
        body="Final human wording",
        recipient="person@example.test",
        actor="local-user",
    )
    approval = store.get_approval(approval_id)
    assert approval["proposal"]["body"] == updated["body"]
    assert approval["proposal"]["subject"] == "Re: Question updated"

    store.decide_approval(approval_id, decision="rejected", actor="local-user")
    rejected_draft = store.get_draft(draft["draft_id"])
    assert rejected_draft["status"] == "draft"
    assert rejected_draft["approval_id"] is None


def test_draft_only_reply_can_be_submitted_for_human_approval(tmp_path):
    service, store, manager, identity = make_service(tmp_path)
    draft = create_reply_draft(store, manager, identity)
    result = service.submit_for_approval(draft["draft_id"], actor="local-user")
    assert result["approval"]["status"] == "pending"
    assert result["approval"]["action"] == "send_reply"
    assert result["draft"]["status"] == "approval_pending"
    assert result["draft"]["approval_id"] == result["approval"]["approval_id"]
