from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mail_agent_gateway.daily_briefing import build_daily_briefing


NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def test_daily_briefing_route_is_read_only_and_wired_into_the_workbench():
    gateway = (ROOT / "apps/gateway/mail_agent_gateway/main_v173.py").read_text(encoding="utf-8")
    workbench = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")
    live = (ROOT / "apps/web/dashboard-live.js").read_text(encoding="utf-8")

    assert '@base.app.get("/v1/briefing")' in gateway
    assert "build_daily_briefing(" in gateway
    assert "calendar_service.events(" in gateway
    assert "'/v1/briefing?limit=20'" in workbench
    assert "Dein Tag ist vorbereitet." in workbench
    assert "data-briefing-view" in workbench
    assert "refreshBriefing(true)" in live


def test_briefing_prioritizes_recovery_security_and_overdue_work():
    result = build_daily_briefing(
        attention=[
            {
                "mailbox_id": "mb_1",
                "remote_id": "mail-security",
                "subject": "Neuer Login",
                "agent_summary": "Unbekannte Anmeldung prüfen.",
                "agent_priority": "high",
                "agent_category": "security",
                "needs_reply": False,
            }
        ],
        approvals=[
            {
                "approval_id": "apr_1",
                "action": "send_reply",
                "status": "approved",
                "execution_status": "uncertain",
                "execution_error": "Versandstatus unklar",
                "proposal": {"mailbox_id": "mb_1", "subject": "Terminbestätigung"},
            }
        ],
        drafts=[],
        conversations=[
            {
                "mailbox_id": "mb_1",
                "thread_id": "thread-overdue",
                "last_message_id": "mail-overdue",
                "status": "to_reply",
                "subject": "Rückfrage",
                "rationale": "Antwort steht noch aus.",
                "due_at": (NOW - timedelta(days=1)).isoformat(),
            }
        ],
        now=NOW,
    )

    assert [item["kind"] for item in result["focus"]] == [
        "recovery",
        "security",
        "follow_up",
    ]
    assert result["counts"]["decisions"] == 3
    assert result["counts"]["overdue"] == 1
    assert result["side_effects"] is False


def test_briefing_deduplicates_attention_and_conversation_for_same_mail():
    result = build_daily_briefing(
        attention=[
            {
                "mailbox_id": "mb_1",
                "remote_id": "mail-1",
                "remote_thread_id": "thread-1",
                "subject": "Bitte antworten",
                "agent_priority": "normal",
                "needs_reply": True,
            }
        ],
        approvals=[],
        drafts=[],
        conversations=[
            {
                "mailbox_id": "mb_1",
                "thread_id": "thread-1",
                "last_message_id": "mail-1",
                "status": "to_reply",
                "subject": "Bitte antworten",
            }
        ],
        now=NOW,
    )

    assert len(result["focus"]) == 1
    assert result["focus"][0]["kind"] == "decision"


def test_briefing_separates_ready_drafts_waiting_threads_and_calendar():
    event = {
        "id": "event-1",
        "summary": "Zahnarzt",
        "start": {"dateTime": "2026-08-24T12:00:00+02:00"},
    }
    result = build_daily_briefing(
        attention=[],
        approvals=[],
        drafts=[
            {
                "draft_id": "draft-ready",
                "mailbox_id": "mb_1",
                "status": "draft",
                "subject": "Vorbereitete Antwort",
                "recipient": "person@example.com",
            },
            {
                "draft_id": "draft-linked",
                "mailbox_id": "mb_1",
                "status": "approval_pending",
                "approval_id": "apr_2",
                "subject": "Bereits in Freigaben",
            },
        ],
        conversations=[
            {
                "mailbox_id": "mb_1",
                "thread_id": "thread-waiting",
                "status": "awaiting_reply",
                "subject": "Angebot",
                "due_at": (NOW + timedelta(days=2)).isoformat(),
            }
        ],
        calendar_events=[event],
        now=NOW,
    )

    assert result["focus"] == []
    assert [item["draft_id"] for item in result["ready_drafts"]] == ["draft-ready"]
    assert result["counts"] == {
        "decisions": 0,
        "ready_drafts": 1,
        "overdue": 0,
        "waiting_on_others": 1,
        "today_events": 1,
    }
    assert result["schedule"] == [event]
    assert result["headline"] == "1 Antwort ist vorbereitet."


def test_briefing_marks_calendar_unavailable_without_failing_mail_summary():
    result = build_daily_briefing(
        attention=[],
        approvals=[],
        drafts=[],
        conversations=[],
        calendar_error="not_connected",
        now=NOW,
    )

    assert result["headline"] == "Du musst gerade nichts entscheiden."
    assert result["calendar"] == {"available": False, "error": "not_connected"}
    assert result["learning"] == {
        "enabled": False,
        "status": "off",
        "confirmed_preferences": 0,
        "pending_suggestions": 0,
        "profile_version": 0,
    }


def test_briefing_exposes_only_owner_controlled_learning_status():
    learning = {
        "enabled": True,
        "status": "active",
        "confirmed_preferences": 3,
        "pending_suggestions": 1,
        "profile_version": 2,
    }
    result = build_daily_briefing(
        attention=[],
        approvals=[],
        drafts=[],
        conversations=[],
        learning=learning,
        now=NOW,
    )

    assert result["learning"] == learning
    assert result["side_effects"] is False
