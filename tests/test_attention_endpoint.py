from __future__ import annotations

from fastapi.testclient import TestClient

from mail_agent_gateway import main_v180
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


def test_attention_endpoint_returns_the_decision_shown_in_briefing(tmp_path, monkeypatch):
    state_store = JsonStateStore(tmp_path / "state.json")
    state_store.write(
        {
            "onboarding_completed": True,
            "configuration": {
                "profile": {
                    "owner_id": "owner",
                    "agent_name": "Nova",
                    "usage_type": "private",
                    "autonomy_mode": "autonomous",
                },
                "behavior": {"enabled": True, "execution_mode": "live"},
            },
            "mailboxes": {
                "mb-1": {
                    "mailbox_id": "mb-1",
                    "email_address": "owner@example.test",
                    "connector": "imap",
                }
            },
        }
    )
    mail_store = MailStore(tmp_path / "mail.db")
    mail_store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb-1",
                uid=1,
                internet_message_id="<decision@example.test>",
                thread_key="thread-1",
                sender="sender@example.test",
                recipients=["owner@example.test"],
                subject="Bitte entscheiden",
                sent_at=None,
                body_text="Kannst du den Termin bestätigen?",
                seen=False,
                remote_id="decision-1",
            )
        ]
    )
    mail_store.update_message_intelligence(
        "mb-1",
        "decision-1",
        priority="high",
        category="work",
        summary="Eine Entscheidung ist erforderlich.",
        needs_reply=True,
    )
    monkeypatch.setattr(main_v180.base, "state_store", state_store)
    monkeypatch.setattr(main_v180.base, "mail_store", mail_store)

    with TestClient(main_v180.app, raise_server_exceptions=False) as client:
        briefing = client.get("/v1/briefing?mailbox_id=mb-1&limit=20")
        attention = client.get("/v1/attention?mailbox_id=mb-1&limit=200")

    assert briefing.status_code == 200
    assert briefing.json()["focus"][0]["message_id"] == "decision-1"
    assert attention.status_code == 200
    assert attention.json()["attention"][0]["remote_id"] == "decision-1"
