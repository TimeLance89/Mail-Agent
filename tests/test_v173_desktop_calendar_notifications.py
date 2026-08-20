from __future__ import annotations

from mail_agent_launcher.desktop_runtime import NotificationTracker, desktop_view_url


def test_calendar_is_a_valid_desktop_deep_link():
    assert desktop_view_url("http://127.0.0.1:8765", "calendar").endswith("/?view=calendar")


def test_autonomous_calendar_outcomes_notify_once_without_mail_content():
    tracker = NotificationTracker()
    baseline = {
        "checks": [],
        "_desktop_calendar_activity": [],
    }
    assert tracker.observe(approvals=[], drafts=[], health=baseline) == []

    completed = {
        "trace_id": "calauto_1",
        "outcome": "calendar_auto_scheduled",
        "last_at": "2026-08-20T19:00:00+00:00",
        "subject": "Secret appointment subject",
        "sender": "private@example.org",
    }
    events = tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_calendar_activity": [completed]},
    )
    assert [(item.title, item.view) for item in events] == [
        ("Termin automatisch übernommen", "calendar")
    ]
    assert "Secret appointment subject" not in events[0].message
    assert "private@example.org" not in events[0].message
    assert tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_calendar_activity": [completed]},
    ) == []


def test_uncertain_autonomous_calendar_request_notifies_attention():
    tracker = NotificationTracker()
    tracker.observe(approvals=[], drafts=[], health={"checks": [], "_desktop_calendar_activity": []})
    event = {
        "trace_id": "calauto_2",
        "outcome": "needs_attention",
        "last_at": "2026-08-20T19:01:00+00:00",
    }
    notifications = tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_calendar_activity": [event]},
    )
    assert [(item.title, item.view) for item in notifications] == [
        ("Terminentscheidung nötig", "attention")
    ]
