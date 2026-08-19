from pathlib import Path

from mail_agent_core.agent import MailMessageContext
from mail_agent_core.brain import AgentBrain
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentProfile,
    AutonomyMode,
    MailActionProposal,
    MailActionType,
    MailCategory,
    MailPriority,
    PolicyDecision,
    UsageType,
)
from mail_agent_gateway.agent_queue import AgentWorkQueue
from mail_agent_gateway.mail_store import MailStore, StoredMessage


def _identity_and_profile(tmp_path: Path):
    identity = IdentityManager(tmp_path / "identity").create(
        owner_id="owner@example.com",
        agent_name="Nova",
        usage_type="private",
    )
    profile = AgentProfile(
        owner_id="owner@example.com",
        agent_name="Nova",
        usage_type=UsageType.PRIVATE,
        autonomy_mode=AutonomyMode.ASSISTANT,
    )
    return identity, profile


def test_brain_creates_soul_memory_and_structured_contact_memory(tmp_path: Path):
    identity, profile = _identity_and_profile(tmp_path)
    brain = AgentBrain(tmp_path / "brain")
    brain.ensure(identity, profile)

    message = MailMessageContext(
        mailbox_id="mb",
        message_id="msg-1",
        sender="alice@example.com",
        subject="Termin morgen",
        body="Passt 10 Uhr?",
    )
    proposal = MailActionProposal(
        action=MailActionType.CREATE_DRAFT,
        mailbox_id="mb",
        message_id="msg-1",
        confidence=0.94,
        summary="Alice fragt nach einem Termin um 10 Uhr.",
        priority=MailPriority.NORMAL,
        category=MailCategory.PERSONAL,
        needs_reply=True,
        body="Ja, 10 Uhr passt.",
    )
    brain.record_analysis(
        message=message,
        proposal=proposal,
        policy=PolicyDecision(allowed=True, requires_approval=False, risk="low", reason="draft"),
    )

    assert (tmp_path / "brain" / "SOUL.md").exists()
    assert "Nova" in (tmp_path / "brain" / "SOUL.md").read_text(encoding="utf-8")
    assert (tmp_path / "brain" / "MEMORY.md").exists()
    context = brain.build_context(message)
    assert "SOUL.md" in context
    assert "alice@example.com" not in context  # sender key is implicit; only structured values are injected
    assert '"interaction_count": 1' in context
    assert brain.public_status()["journal_events"] == 1


def test_owner_memory_survives_future_brain_initialization(tmp_path: Path):
    identity, profile = _identity_and_profile(tmp_path)
    brain = AgentBrain(tmp_path / "brain")
    brain.ensure(identity, profile)
    brain.update_owner_memory(memory="# MEMORY.md\n\n- Rechnungen immer knapp zusammenfassen.")

    # ensure() runs on every analysis and must never reset owner-maintained memory.
    brain.ensure(identity, profile)

    assert "Rechnungen immer knapp" in (tmp_path / "brain" / "MEMORY.md").read_text(encoding="utf-8")


def _message(uid: int) -> StoredMessage:
    return StoredMessage(
        mailbox_id="mb",
        uid=uid,
        internet_message_id=f"<msg-{uid}@example>",
        thread_key=f"thread-{uid}",
        sender="sender@example.com",
        recipients=["owner@example.com"],
        subject=f"Mail {uid}",
        sent_at=None,
        body_text="Body",
        seen=False,
        remote_id=f"remote-{uid}",
    )


def test_work_queue_reaches_older_unprocessed_mail(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(uid) for uid in range(1, 31)])

    # Simulate the old runtime having processed the newest 20 messages.
    for uid in range(11, 31):
        store.record_agent_processing("mb", f"remote-{uid}", status="processed")

    queue = AgentWorkQueue(store)
    pending = queue.list_pending("mb", 5)

    assert queue.pending_count("mb") == 10
    assert [item["uid"] for item in pending] == [10, 9, 8, 7, 6]


def test_work_queue_prioritizes_never_attempted_mail_over_retry_errors(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1), _message(2), _message(3)])
    store.record_agent_processing("mb", "remote-3", status="error", error="temporary provider outage")

    queue = AgentWorkQueue(store)
    pending = queue.list_pending("mb", 3)

    assert [item["uid"] for item in pending] == [2, 1, 3]
