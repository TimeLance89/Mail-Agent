from __future__ import annotations

from mail_agent_core.brain import AgentBrain
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentProfile,
    AutonomyMode,
    MailActionProposal,
    MailActionType,
    UsageType,
)
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.signature import stamp_outgoing_proposal
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.draft_service import DraftService
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


def _identity_profile_brain(tmp_path):
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="work")
    profile = AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.WORK,
        autonomy_mode=AutonomyMode.COPILOT,
        email_signature="Viele Grüße",
    )
    brain = AgentBrain(tmp_path / "brain")
    brain.ensure(identity, profile)
    return manager, identity, profile, brain


def _shortening_bodies():
    before = "Hallo,\n\n" + ("Das ist ein sehr ausführlicher Satz mit unnötigem Kontext. " * 10) + "\n\nViele Grüße"
    after = "Hallo,\n\nJa, das passt für mich.\n\nViele Grüße"
    return before, after


def test_repeated_owner_edits_create_candidate_but_do_not_learn_automatically(tmp_path):
    _manager, _identity, _profile, brain = _identity_profile_brain(tmp_path)
    before, after = _shortening_bodies()
    initial_memory = brain.snapshot().memory

    for index in range(3):
        brain.record_owner_edit(
            draft_id=f"dr-{index}",
            mailbox_id="mb",
            message_id=f"msg-{index}",
            sender="person@example.test",
            before_subject="Re: Frage",
            before_body=before,
            after_subject="Re: Frage",
            after_body=after,
        )

    candidates = brain.learning_candidates()
    assert any(item["candidate_id"] == "prefer-shorter-replies" for item in candidates)
    assert brain.snapshot().memory == initial_memory
    assert brain.public_status()["feedback_events"] == 3


def test_learning_is_written_only_after_explicit_acceptance(tmp_path):
    _manager, _identity, _profile, brain = _identity_profile_brain(tmp_path)
    before, after = _shortening_bodies()
    for index in range(3):
        brain.record_owner_edit(
            draft_id=f"dr-{index}",
            mailbox_id="mb",
            message_id=f"msg-{index}",
            sender=None,
            before_subject="Betreff",
            before_body=before,
            after_subject="Betreff",
            after_body=after,
        )

    accepted = brain.accept_learning("prefer-shorter-replies")
    assert accepted["evidence_count"] == 3
    assert "kurz und prägnant" in brain.snapshot().memory
    assert brain.learning_candidates() == []
    assert brain.recent_activity(1)[0]["kind"] == "learning_accepted"


def test_rejected_learning_does_not_modify_memory(tmp_path):
    _manager, _identity, _profile, brain = _identity_profile_brain(tmp_path)
    before, after = _shortening_bodies()
    initial = brain.snapshot().memory
    for index in range(3):
        brain.record_owner_edit(
            draft_id=f"dr-{index}",
            mailbox_id="mb",
            message_id=None,
            sender=None,
            before_subject="Betreff",
            before_body=before,
            after_subject="Betreff",
            after_body=after,
        )

    brain.reject_learning("prefer-shorter-replies")
    assert brain.snapshot().memory == initial
    assert brain.learning_candidates() == []


def test_draft_service_records_owner_feedback_without_storing_full_mail_text(tmp_path):
    manager, identity, profile, brain = _identity_profile_brain(tmp_path)
    store = MailStore(tmp_path / "mail.db")
    state = JsonStateStore(tmp_path / "state.json")
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
                body_text="Untrusted sender content must not become durable owner memory.",
                seen=False,
            )
        ]
    )
    before, after = _shortening_bodies()
    proposal = MailActionProposal(
        action=MailActionType.CREATE_DRAFT,
        mailbox_id="mb",
        message_id="1",
        thread_id="thread",
        recipient="person@example.test",
        subject="Re: Question",
        body=before,
        confidence=0.95,
        metadata={"drafted_from_action": "send_reply"},
    )
    proposal = stamp_outgoing_proposal(
        proposal,
        identity,
        sign_payload=manager.sign,
        user_signature=profile.email_signature,
    )
    draft = store.create_draft(proposal)
    service = DraftService(
        mail_store=store,
        identity_manager=manager,
        state_store=state,
        policy_engine=PolicyEngine(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        brain=brain,
    )

    service.edit(
        draft["draft_id"],
        subject="Re: Question",
        body=after,
        recipient="person@example.test",
        actor="local-user",
    )

    assert brain.public_status()["feedback_events"] == 1
    feedback_text = brain.feedback_path.read_text(encoding="utf-8")
    assert "Untrusted sender content" not in feedback_text
    assert before not in feedback_text
    assert after not in feedback_text
    assert '"length_signal": "shorter"' in feedback_text


def test_cycle_status_is_visible_in_brain_activity(tmp_path):
    _manager, _identity, _profile, brain = _identity_profile_brain(tmp_path)
    brain.record_cycle(
        {
            "mailbox_id": "mb",
            "processed": 0,
            "skipped": "outside_schedule",
            "pending_before": 12,
            "pending_after": 12,
        }
    )

    event = brain.recent_activity(1)[0]
    assert event["kind"] == "cycle"
    assert event["skipped"] == "outside_schedule"
    assert event["pending_after"] == 12
