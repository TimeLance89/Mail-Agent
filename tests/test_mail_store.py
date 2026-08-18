from pathlib import Path

import pytest

from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.mail_store import MailStore, StoredMessage


def test_mail_store_persists_messages_and_sync_cursor(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    stored = StoredMessage(
        mailbox_id="mb_one",
        uid=42,
        internet_message_id="<one@example.com>",
        thread_key="thread",
        sender="sender@example.com",
        recipients=["me@example.com"],
        subject="Hello",
        sent_at="2026-08-18T12:00:00+00:00",
        body_text="Body",
        seen=False,
    )
    assert store.upsert_messages([stored]) == 1
    store.record_sync("mb_one", last_uid=42)

    messages = store.list_messages("mb_one")
    assert messages[0]["uid"] == 42
    assert messages[0]["recipients"] == ["me@example.com"]
    assert messages[0]["seen"] is False
    assert store.get_last_uid("mb_one") == 42
    assert store.sync_status("mb_one")["last_error"] is None


def test_approval_queue_can_only_be_decided_once(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY,
        mailbox_id="mb_one",
        message_id="42",
        recipient="person@example.com",
        body="Hello",
    )
    policy = PolicyDecision(
        allowed=True,
        requires_approval=True,
        risk="high",
        reason="Human approval required",
    )
    approval = store.enqueue_approval(proposal, policy)
    assert approval["status"] == "pending"
    assert len(store.list_approvals("pending")) == 1

    decided = store.decide_approval(approval["approval_id"], decision="approved", actor="owner")
    assert decided["status"] == "approved"
    assert decided["decided_by"] == "owner"

    with pytest.raises(RuntimeError):
        store.decide_approval(approval["approval_id"], decision="rejected", actor="other")


def test_draft_pipeline_persists_model_generated_reply(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY,
        mailbox_id="mb_one",
        message_id="42",
        thread_id="thread-1",
        recipient="person@example.com",
        subject="Re: Hello",
        body="Thanks for your message.",
    )
    draft = store.create_draft(proposal, approval_id="apr_123")
    assert draft["status"] == "approval_pending"
    assert draft["approval_id"] == "apr_123"
    assert store.list_drafts("mb_one")[0]["body"] == "Thanks for your message."
