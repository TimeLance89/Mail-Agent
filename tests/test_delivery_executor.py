from __future__ import annotations

import asyncio

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_core.signature import stamp_outgoing_proposal
from mail_agent_gateway.action_executor import MailActionExecutor
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore, StoredMessage


class FakeVault:
    def contains(self, reference: str) -> bool:
        return reference == "secret"

    def get_secret(self, reference: str) -> str:
        assert reference == "secret"
        return "password"


def _approved_reply(tmp_path):
    store = MailStore(tmp_path / "mail.db")
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="private")
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<source@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Hello",
                sent_at=None,
                body_text="Question",
                seen=False,
            )
        ]
    )
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY,
        mailbox_id="mb",
        message_id="1",
        thread_id="thread",
        recipient="person@example.test",
        subject="Re: Hello",
        body="Answer",
        confidence=0.95,
    )
    proposal = stamp_outgoing_proposal(
        proposal,
        identity,
        sign_payload=manager.sign,
    )
    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="send"),
    )
    store.decide_approval(approval["approval_id"], decision="approved", actor="user")
    return store, manager, approval["approval_id"]


def test_approved_smtp_reply_is_sent_once(monkeypatch, tmp_path):
    store, manager, approval_id = _approved_reply(tmp_path)
    calls = []

    def fake_send(self, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("mail_agent_gateway.action_executor.SmtpSender.send", fake_send)
    executor = MailActionExecutor(
        mail_store=store,
        identity_manager=manager,
        vault=FakeVault(),
        mailbox_lookup=lambda _mailbox_id: {
            "mailbox_id": "mb",
            "email_address": "owner@example.test",
            "username": "owner@example.test",
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "smtp_host": "smtp.example.test",
            "smtp_port": 465,
            "credential_ref": "secret",
        },
        google_client_id="",
        google_client_secret=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    first = asyncio.run(executor.execute_approval(approval_id))
    second = asyncio.run(executor.execute_approval(approval_id))

    assert first["execution_status"] == "sent"
    assert second["execution_status"] == "sent"
    assert len(calls) == 1
    assert calls[0]["to"] == "person@example.test"
    assert calls[0]["in_reply_to"] == "<source@example.test>"


def test_tampered_signed_reply_is_rejected_before_network(monkeypatch, tmp_path):
    store, manager, approval_id = _approved_reply(tmp_path)
    with store._connect() as conn:
        row = conn.execute("SELECT proposal_json FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        proposal_json = row["proposal_json"].replace("Answer", "Changed after signing", 1)
        conn.execute("UPDATE approvals SET proposal_json=? WHERE approval_id=?", (proposal_json, approval_id))

    called = False

    def fake_send(self, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("mail_agent_gateway.action_executor.SmtpSender.send", fake_send)
    executor = MailActionExecutor(
        mail_store=store,
        identity_manager=manager,
        vault=FakeVault(),
        mailbox_lookup=lambda _mailbox_id: {
            "mailbox_id": "mb",
            "email_address": "owner@example.test",
            "username": "owner@example.test",
            "imap_host": "imap.example.test",
            "smtp_host": "smtp.example.test",
            "credential_ref": "secret",
        },
        google_client_id="",
        google_client_secret=None,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    try:
        asyncio.run(executor.execute_approval(approval_id))
    except RuntimeError as exc:
        assert "signature" in str(exc).lower()
    else:
        raise AssertionError("tampered signed message was not rejected")
    assert called is False
    assert store.get_approval(approval_id)["execution_status"] == "failed"