from __future__ import annotations

from pathlib import Path

from mail_agent_gateway.mail_store import MailStore, StoredMessage


def _message(uid: int) -> StoredMessage:
    return StoredMessage(
        mailbox_id="mb-1",
        uid=uid,
        internet_message_id=f"<m-{uid}@example.test>",
        thread_key=f"thread-{uid}",
        sender="sender@example.test",
        recipients=["owner@example.test"],
        subject=f"Message {uid}",
        sent_at=None,
        body_text="hello",
        seen=False,
        remote_id=f"remote-{uid}",
    )


def test_attention_collects_important_and_reply_needed_mail(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1), _message(2), _message(3)])
    store.update_message_intelligence("mb-1", "remote-1", priority="high", category="work", summary="Important", needs_reply=False)
    store.update_message_intelligence("mb-1", "remote-2", priority="normal", category="support", summary="Reply", needs_reply=True)
    store.update_message_intelligence("mb-1", "remote-3", priority="normal", category="newsletter", summary="Noise", needs_reply=False)

    items = store.list_attention("mb-1")
    assert {item["remote_id"] for item in items} == {"remote-1", "remote-2"}

    store.resolve_attention("mb-1", "remote-1", owner_note="Erledigt")
    items = store.list_attention("mb-1")
    assert {item["remote_id"] for item in items} == {"remote-2"}
