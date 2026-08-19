from __future__ import annotations

from mail_agent_core.shadow import ShadowReportStore


def test_shadow_report_store_never_persists_mail_bodies_or_prompts(tmp_path):
    store = ShadowReportStore(tmp_path / "shadow.jsonl")
    report = store.save_report(
        run_id="shadow_1",
        mailbox_id="mb",
        requested=1,
        started_at="2026-08-19T08:00:00+00:00",
        results=[
            {
                "message_id": "m1",
                "sender": "person@example.test",
                "subject": "Test",
                "action": "create_draft",
                "confidence": 0.93,
                "simulated_outcome": "would_draft",
                "planned_artifacts": ["draft"],
                "body": "SECRET MAIL BODY",
                "prompt": "SECRET PROMPT",
                "token": "SECRET TOKEN",
            }
        ],
    )

    assert report["side_effects"] == 0
    assert report["outcomes"] == {"would_draft": 1}
    assert report["results"][0]["planned_artifacts"] == ["draft"]
    raw = (tmp_path / "shadow.jsonl").read_text(encoding="utf-8")
    assert "SECRET MAIL BODY" not in raw
    assert "SECRET PROMPT" not in raw
    assert "SECRET TOKEN" not in raw
    assert '"body"' not in raw
    assert '"prompt"' not in raw


def test_shadow_report_store_filters_by_mailbox(tmp_path):
    store = ShadowReportStore(tmp_path / "shadow.jsonl")
    for mailbox in ("a", "b"):
        store.save_report(
            run_id=f"run_{mailbox}",
            mailbox_id=mailbox,
            requested=0,
            started_at="2026-08-19T08:00:00+00:00",
            results=[],
        )
    reports = store.recent_reports(mailbox_id="a")
    assert [item["run_id"] for item in reports] == ["run_a"]
