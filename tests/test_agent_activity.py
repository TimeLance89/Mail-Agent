from __future__ import annotations

from mail_agent_core.activity import AgentActivityStore


def test_activity_store_groups_privacy_minimized_trace(tmp_path):
    store = AgentActivityStore(tmp_path / "activity.jsonl")
    trace_id = store.begin_message(
        mailbox_id="mb_1",
        message_id="m_1",
        thread_id="t_1",
        sender="Sender@Example.com",
        subject="Rechnung August",
        provider="ollama",
        model="qwen",
        trigger="cycle",
    )
    store.record(
        trace_id=trace_id,
        stage="llm",
        status="completed",
        detail="Analyse abgeschlossen",
        duration_ms=123,
        data={
            "provider": "ollama",
            "model": "qwen",
            "action": "create_draft",
            "body": "DIES DARF NICHT GESPEICHERT WERDEN",
            "prompt": "AUCH NICHT",
        },
    )
    store.record(
        trace_id=trace_id,
        stage="policy",
        status="completed",
        detail="High-impact action requires approval",
        data={"allowed": True, "requires_approval": True, "risk": "high"},
    )
    store.finish(trace_id, outcome="approval_required", reason="Wartet auf Freigabe")

    traces = store.recent_traces()
    assert len(traces) == 1
    trace = traces[0]
    assert trace["trace_id"] == trace_id
    assert trace["sender"] == "sender@example.com"
    assert trace["outcome"] == "approval_required"
    assert [step["stage"] for step in trace["steps"]] == ["queued", "llm", "policy", "finished"]
    assert trace["steps"][1]["duration_ms"] == 123

    raw = (tmp_path / "activity.jsonl").read_text(encoding="utf-8")
    assert "DIES DARF NICHT GESPEICHERT WERDEN" not in raw
    assert "AUCH NICHT" not in raw
    assert '"body"' not in raw
    assert '"prompt"' not in raw


def test_activity_summary_separates_sync_and_mail_traces(tmp_path):
    store = AgentActivityStore(tmp_path / "activity.jsonl")
    store.record_sync(
        mailbox_id="mb_1",
        status="completed",
        detail="Postfach erfolgreich synchronisiert",
        connector="gmail_api",
        messages_synced=4,
    )
    trace_id = store.begin_message(
        mailbox_id="mb_1",
        message_id="m_1",
        thread_id=None,
        sender="a@example.com",
        subject="Hallo",
        provider="codex",
        model="default",
        trigger="manual",
    )
    store.record(
        trace_id=trace_id,
        stage="llm",
        status="completed",
        duration_ms=200,
        data={"provider": "codex", "model": "default"},
    )
    store.finish(trace_id, outcome="draft_created", reason="Entwurf erstellt")

    summary = store.summary(mailbox_id="mb_1")
    assert summary["trace_count"] == 1
    assert summary["sync_trace_count"] == 1
    assert summary["outcomes"]["draft_created"] == 1
    assert summary["avg_llm_ms"] == 200


def test_activity_store_tolerates_corrupt_jsonl(tmp_path):
    path = tmp_path / "activity.jsonl"
    path.write_text("{broken\n", encoding="utf-8")
    store = AgentActivityStore(path)
    trace_id = store.begin_message(
        mailbox_id="mb_1",
        message_id="m_1",
        thread_id=None,
        sender="a@example.com",
        subject="Test",
        provider="ollama",
        model="x",
        trigger="cycle",
    )
    store.finish(trace_id, outcome="no_action", reason="nichts nötig")
    assert store.recent_traces(5)[0]["outcome"] == "no_action"
