from __future__ import annotations

import asyncio

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_core.signature import stamp_outgoing_proposal
from mail_agent_gateway.action_executor import MailActionExecutor
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_microsoft.client import GRAPH_SCOPES


class EmptyVault:
    def contains(self, _reference: str) -> bool:
        return False


class FakeMicrosoft:
    def __init__(self):
        self.read = []
        self.archived = []
        self.moved = []
        self.trashed = []
        self.replies = []
        self.forwards = []

    async def mark_read(self, message_id):
        self.read.append(message_id)
        return {"id": message_id, "isRead": True}

    async def archive_message(self, message_id):
        self.archived.append(message_id)
        return {"id": "archived-copy"}

    async def resolve_folder_id(self, name):
        assert name == "Projects"
        return "folder-projects"

    async def move_message(self, message_id, destination_id):
        self.moved.append((message_id, destination_id))
        return {"id": "moved-copy"}

    async def trash_message(self, message_id):
        self.trashed.append(message_id)
        return {"id": "trash-copy"}

    async def send_reply(self, **kwargs):
        self.replies.append(kwargs)
        return {"id": "reply-draft", "conversationId": "conv-1"}

    async def send_forward(self, **kwargs):
        self.forwards.append(kwargs)
        return {"id": "forward-draft", "conversationId": "conv-1"}


def make_executor(tmp_path):
    store = MailStore(tmp_path / "mail.db")
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="private")
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb-ms",
                uid=42,
                internet_message_id="<source@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Hello",
                sent_at=None,
                body_text="Question",
                seen=False,
                remote_id="graph-message-1",
                remote_thread_id="conv-1",
                connector="microsoft_graph",
            )
        ]
    )
    executor = MailActionExecutor(
        mail_store=store,
        identity_manager=manager,
        vault=EmptyVault(),
        mailbox_lookup=lambda _mailbox_id: {
            "mailbox_id": "mb-ms",
            "connector": "microsoft_graph",
            "email_address": "owner@example.test",
            "credential_ref": "oauth",
        },
        google_client_id="",
        google_client_secret=None,
        microsoft_client_id="ms-client",
        microsoft_tenant="common",
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    fake = FakeMicrosoft()

    async def fake_client(_mailbox):
        return fake

    executor._microsoft_client = fake_client
    return executor, store, manager, identity, fake


def test_microsoft_oauth_requests_only_required_mail_capabilities():
    assert "Mail.ReadWrite" in GRAPH_SCOPES
    assert "Mail.Send" in GRAPH_SCOPES
    assert "offline_access" in GRAPH_SCOPES


def test_microsoft_mark_read_and_move_execute_directly(tmp_path):
    executor, store, _manager, _identity, fake = make_executor(tmp_path)
    read = MailActionProposal(
        action=MailActionType.MARK_READ,
        mailbox_id="mb-ms",
        message_id="graph-message-1",
        confidence=0.95,
    )
    result = asyncio.run(executor.execute_direct(read))
    assert result["connector"] == "microsoft_graph"
    assert fake.read == ["graph-message-1"]
    assert store.get_message("mb-ms", "graph-message-1")["seen"] is True

    move = MailActionProposal(
        action=MailActionType.MOVE,
        mailbox_id="mb-ms",
        message_id="graph-message-1",
        destination_folder="Projects",
        confidence=0.95,
    )
    result = asyncio.run(executor.execute_direct(move))
    assert result["destination"] == "Projects"
    assert fake.moved == [("graph-message-1", "folder-projects")]
    assert store.get_message("mb-ms", "graph-message-1") is None


def test_microsoft_delete_requires_approval_and_soft_deletes(tmp_path):
    executor, store, _manager, _identity, fake = make_executor(tmp_path)
    proposal = MailActionProposal(
        action=MailActionType.DELETE,
        mailbox_id="mb-ms",
        message_id="graph-message-1",
        confidence=0.95,
    )
    try:
        asyncio.run(executor.execute_direct(proposal))
    except RuntimeError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("Microsoft delete bypassed approval")

    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="delete"),
    )
    store.decide_approval(approval["approval_id"], decision="approved", actor="owner")
    completed = asyncio.run(executor.execute_approval(approval["approval_id"]))
    assert completed["execution_status"] == "completed"
    assert fake.trashed == ["graph-message-1"]
    assert store.get_message("mb-ms", "graph-message-1") is None


def _approved_outbound(tmp_path, action: MailActionType, recipient: str):
    executor, store, manager, identity, fake = make_executor(tmp_path)
    proposal = MailActionProposal(
        action=action,
        mailbox_id="mb-ms",
        message_id="graph-message-1",
        thread_id="thread",
        recipient=recipient,
        subject="Re: Hello" if action == MailActionType.SEND_REPLY else "Fwd: Hello",
        body="Answer" if action == MailActionType.SEND_REPLY else "Forward note",
        confidence=0.98,
    )
    signed = stamp_outgoing_proposal(proposal, identity, sign_payload=manager.sign)
    approval = store.enqueue_approval(
        signed,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="send"),
    )
    store.decide_approval(approval["approval_id"], decision="approved", actor="owner")
    return executor, store, fake, approval["approval_id"]


def test_microsoft_signed_reply_uses_real_reply_chain_once(tmp_path):
    executor, store, fake, approval_id = _approved_outbound(
        tmp_path,
        MailActionType.SEND_REPLY,
        "person@example.test",
    )
    first = asyncio.run(executor.execute_approval(approval_id))
    second = asyncio.run(executor.execute_approval(approval_id))

    assert first["execution_status"] == "sent"
    assert second["execution_status"] == "sent"
    assert len(fake.replies) == 1
    assert fake.replies[0]["source_message_id"] == "graph-message-1"
    assert fake.replies[0]["recipient"] == "person@example.test"
    assert "MAIL-AGENT-ID" in fake.replies[0]["body"]


def test_microsoft_signed_forward_uses_native_forward_chain_once(tmp_path):
    executor, store, fake, approval_id = _approved_outbound(
        tmp_path,
        MailActionType.FORWARD,
        "colleague@example.test",
    )
    first = asyncio.run(executor.execute_approval(approval_id))
    second = asyncio.run(executor.execute_approval(approval_id))

    assert first["execution_status"] == "sent"
    assert second["execution_status"] == "sent"
    assert len(fake.forwards) == 1
    assert fake.forwards[0]["source_message_id"] == "graph-message-1"
    assert fake.forwards[0]["recipient"] == "colleague@example.test"
    assert "MAIL-AGENT-ID" in fake.forwards[0]["body"]
