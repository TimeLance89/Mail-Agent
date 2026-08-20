from __future__ import annotations

from mail_agent_launcher.desktop_runtime import (
    DesktopGatewayClient,
    NotificationTracker,
    desktop_view_url,
    summarize_desktop_status,
)


def test_desktop_view_url_only_allows_known_views():
    assert desktop_view_url("http://127.0.0.1:8765", "approvals").endswith("/?view=approvals")
    assert desktop_view_url("http://127.0.0.1:8765", "attention").endswith("/?view=attention")
    assert desktop_view_url("http://127.0.0.1:8765", "not-a-view").endswith("/?view=overview")


def test_desktop_status_prioritizes_recovery_then_pause_shadow_and_work():
    base = {
        "settings": {"behavior": {"enabled": True, "execution_mode": "live"}},
        "brain": {"pending_total": 0},
        "approvals": [],
        "drafts": [],
        "health": {"overall": "ok"},
    }
    assert summarize_desktop_status(**base).key == "active"

    work = dict(base, brain={"pending_total": 3})
    assert summarize_desktop_status(**work).key == "work"

    shadow = dict(
        work,
        settings={"behavior": {"enabled": True, "execution_mode": "shadow"}},
    )
    assert summarize_desktop_status(**shadow).key == "shadow"

    paused = dict(
        shadow,
        settings={"behavior": {"enabled": False, "execution_mode": "shadow"}},
    )
    assert summarize_desktop_status(**paused).key == "paused"

    recovery = dict(paused, health={"overall": "action_required"})
    assert summarize_desktop_status(**recovery).key == "error"


def test_notification_tracker_baselines_existing_work_and_deduplicates():
    tracker = NotificationTracker()
    health = {"checks": [{"id": "storage", "status": "ok"}]}
    assert tracker.observe(
        approvals=[{"approval_id": "a1"}],
        drafts=[{"draft_id": "d1", "status": "draft"}],
        health=health,
    ) == []

    events = tracker.observe(
        approvals=[{"approval_id": "a1"}, {"approval_id": "a2"}],
        drafts=[
            {"draft_id": "d1", "status": "draft"},
            {"draft_id": "d2", "status": "draft"},
        ],
        health={
            "checks": [
                {"id": "storage", "status": "ok"},
                {"id": "llm_provider", "status": "error"},
            ]
        },
    )
    assert [event.view for event in events] == ["approvals", "drafts", "system"]
    assert tracker.observe(
        approvals=[{"approval_id": "a1"}, {"approval_id": "a2"}],
        drafts=[
            {"draft_id": "d1", "status": "draft"},
            {"draft_id": "d2", "status": "draft"},
        ],
        health={"checks": [{"id": "llm_provider", "status": "error"}]},
    ) == []


def test_health_warnings_cover_sync_provider_and_recovery():
    tracker = NotificationTracker()
    tracker.observe(approvals=[], drafts=[], health={"checks": []})

    sync_events = tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [{"id": "mailbox:mb_1", "status": "warning"}]},
    )
    assert [(event.title, event.view) for event in sync_events] == [
        ("Postfach prüfen", "system")
    ]

    provider_events = tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [{"id": "provider", "status": "error"}]},
    )
    assert [(event.title, event.view) for event in provider_events] == [
        ("KI-Provider prüfen", "system")
    ]

    recovery_events = tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [{"id": "execution", "status": "warning"}]},
    )
    assert [(event.title, event.view) for event in recovery_events] == [
        ("Mail-Aktion prüfen", "approvals")
    ]


def test_priority_mail_notifications_are_baselined_deduplicated_and_privacy_safe():
    tracker = NotificationTracker()
    baseline = {
        "checks": [],
        "_desktop_priority_messages": [
            {
                "mailbox_id": "mb1",
                "remote_id": "m1",
                "sender": "private@example.org",
                "subject": "Sensitive subject",
                "agent_priority": "high",
                "agent_category": "work",
                "needs_reply": False,
            }
        ],
    }
    assert tracker.observe(approvals=[], drafts=[], health=baseline) == []

    updated = {
        "checks": [],
        "_desktop_priority_messages": baseline["_desktop_priority_messages"]
        + [
            {
                "mailbox_id": "mb1",
                "remote_id": "m2",
                "sender": "secret@example.org",
                "subject": "Do not expose this",
                "agent_priority": "urgent",
                "agent_category": "security",
                "needs_reply": True,
            }
        ],
    }
    events = tracker.observe(approvals=[], drafts=[], health=updated)
    assert [(event.title, event.view) for event in events] == [
        ("Dringende E-Mail erkannt", "attention")
    ]
    assert "secret@example.org" not in events[0].message
    assert "Do not expose this" not in events[0].message
    assert tracker.observe(approvals=[], drafts=[], health=updated) == []


def test_security_mail_only_escalates_when_reply_is_needed():
    tracker = NotificationTracker()
    tracker.observe(approvals=[], drafts=[], health={"checks": []})

    ignored = tracker.observe(
        approvals=[],
        drafts=[],
        health={
            "checks": [],
            "_desktop_priority_messages": [
                {
                    "mailbox_id": "mb1",
                    "remote_id": "normal-security",
                    "agent_priority": "normal",
                    "agent_category": "security",
                    "needs_reply": False,
                }
            ],
        },
    )
    assert ignored == []

    escalated = tracker.observe(
        approvals=[],
        drafts=[],
        health={
            "checks": [],
            "_desktop_priority_messages": [
                {
                    "mailbox_id": "mb1",
                    "remote_id": "security-reply",
                    "agent_priority": "normal",
                    "agent_category": "security",
                    "needs_reply": True,
                }
            ],
        },
    )
    assert [(event.title, event.view) for event in escalated] == [
        ("Sicherheitsrelevante E-Mail erkannt", "attention")
    ]


def test_draft_with_approval_only_notifies_as_approval():
    tracker = NotificationTracker()
    tracker.observe(approvals=[], drafts=[], health={"checks": []})
    events = tracker.observe(
        approvals=[{"approval_id": "a1"}],
        drafts=[{"draft_id": "d1", "status": "pending_approval", "approval_id": "a1"}],
        health={"checks": []},
    )
    assert [event.view for event in events] == ["approvals"]


def test_gateway_client_pause_preserves_existing_behavior(monkeypatch):
    client = DesktopGatewayClient("http://127.0.0.1:8765")
    calls = []

    def fake_request(path, *, method="GET", payload=None):
        calls.append((path, method, payload))
        if path == "/v1/settings" and method == "GET":
            return {
                "behavior": {
                    "enabled": True,
                    "execution_mode": "shadow",
                    "minimum_confidence": 0.81,
                    "rules": [{"pattern": "@example.org", "mode": "draft_only"}],
                }
            }
        return {"behavior": payload["behavior"]}

    monkeypatch.setattr(client, "request", fake_request)
    result = client.set_enabled(False)
    behavior = calls[-1][2]["behavior"]
    assert behavior["enabled"] is False
    assert behavior["execution_mode"] == "shadow"
    assert behavior["minimum_confidence"] == 0.81
    assert behavior["rules"] == [{"pattern": "@example.org", "mode": "draft_only"}]
    assert result["behavior"]["enabled"] is False


def test_gateway_snapshot_collects_recent_messages_for_desktop_priority_notifications(monkeypatch):
    client = DesktopGatewayClient("http://127.0.0.1:8765")

    def fake_request(path, *, method="GET", payload=None):
        if path == "/v1/settings":
            return {"behavior": {"enabled": True, "execution_mode": "live"}}
        if path == "/v1/agent/brain":
            return {"pending_total": 0}
        if path.startswith("/v1/approvals"):
            return {"approvals": []}
        if path.startswith("/v1/drafts"):
            return {"drafts": []}
        if path == "/v1/system/health":
            return {"overall": "ok", "checks": []}
        if path == "/v1/mailboxes":
            return {"mailboxes": [{"mailbox_id": "mb1"}, {"mailbox_id": "mb2"}]}
        if path == "/v1/mailboxes/mb1/messages?limit=50":
            return {"messages": [{"mailbox_id": "mb1", "remote_id": "m1", "agent_priority": "high"}]}
        if path == "/v1/mailboxes/mb2/messages?limit=50":
            return {"messages": [{"mailbox_id": "mb2", "remote_id": "m2", "agent_priority": "normal"}]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake_request)
    snapshot = client.snapshot()
    messages = snapshot["health"]["_desktop_priority_messages"]
    assert [item["remote_id"] for item in messages] == ["m1", "m2"]
