from __future__ import annotations

import asyncio

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.action_executor import MailActionExecutor
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore, StoredMessage


class EmptyVault:
    def contains(self, _reference: str) -> bool:
        return False


class FakeGmail:
    def __init__(self):
        self.modified = []
        self.trashed = []

    async def modify_message(self, message_id, *, add_label_ids=None, remove_label_ids=None):
        self.modified.append((message_id, add_label_ids or [], remove_label_ids or []))
        return {"id": message_id}

    async def trash_message(self, message_id):
        self.trashed.append(message_id)
        return {"id": message_id}

    async def resolve_label_id(self, name):
        assert name == "Projects"
        return "Label_42"


def make_executor(tmp_path):
    store = MailStore(tmp_path / "mail.db")
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner", agent_name="Nova", usage_type="private")
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<m@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Hello",
                sent_at=None,
                body_text="Body",
                seen=False,
                remote_id="gmail-1",
                remote_thread_id="thread-1",
                connector="gmail_api",
            )
        ]
    )
    executor = MailActionExecutor(
        mail_store=store,
        identity_manager=identity,
        vault=EmptyVault(),
        mailbox_lookup=lambda _mailbox_id: {
            "mailbox_id": "mb",
            "connector": "gmail_api",
            "email_address": "owner@example.test",
        },
        google_client_id="client",
        google_client_secret=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    fake = FakeGmail()

    async def fake_google_client(_mailbox):
        return fake

    executor._google_client = fake_google_client
    return executor, store, fake


def test_mark_read_can_execute_directly_and_updates_local_state(tmp_path):
    executor, store, fake = make_executor(tmp_path)
    proposal = MailActionProposal(
        action=MailActionType.MARK_READ,
        mailbox_id="mb",
        message_id="gmail-1",
        confidence=0.9,
    )
    result = asyncio.run(executor.execute_direct(proposal))
    assert result["action"] == "mark_read"
    assert fake.modified == [("gmail-1", [], ["UNREAD"])]
    assert store.get_message("mb", "gmail-1")["seen"] is True


def test_move_uses_existing_gmail_label_and_removes_local_inbox_row(tmp_path):
    executor, store, fake = make_executor(tmp_path)
    proposal = MailActionProposal(
        action=MailActionType.MOVE,
        mailbox_id="mb",
        message_id="gmail-1",
        destination_folder="Projects",
        confidence=0.9,
    )
    result = asyncio.run(executor.execute_direct(proposal))
    assert result["destination"] == "Projects"
    assert fake.modified == [("gmail-1", ["Label_42"], ["INBOX"])]
    assert store.get_message("mb", "gmail-1") is None


def test_delete_cannot_bypass_approval_but_approved_delete_moves_to_trash(tmp_path):
    executor, store, fake = make_executor(tmp_path)
    proposal = MailActionProposal(
        action=MailActionType.DELETE,
        mailbox_id="mb",
        message_id="gmail-1",
        confidence=0.9,
    )
    try:
        asyncio.run(executor.execute_direct(proposal))
    except RuntimeError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("delete bypassed approval")

    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="delete"),
    )
    store.decide_approval(approval["approval_id"], decision="approved", actor="user")
    completed = asyncio.run(executor.execute_approval(approval["approval_id"]))
    assert completed["execution_status"] == "completed"
    assert fake.trashed == ["gmail-1"]
    assert store.get_message("mb", "gmail-1") is None
