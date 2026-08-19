from __future__ import annotations

from mail_agent_launcher.desktop_runtime import NotificationTracker


def test_priority_message_is_not_notified_twice_after_reclassification_gap():
    tracker = NotificationTracker()
    high = {
        "mailbox_id": "mb1",
        "remote_id": "m1",
        "agent_priority": "high",
        "agent_category": "work",
        "needs_reply": True,
    }

    tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_priority_messages": [high]},
    )
    assert tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_priority_messages": []},
    ) == []
    assert tracker.observe(
        approvals=[],
        drafts=[],
        health={"checks": [], "_desktop_priority_messages": [high]},
    ) == []
