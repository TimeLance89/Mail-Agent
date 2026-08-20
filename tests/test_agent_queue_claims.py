from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mail_agent_gateway.agent_queue import AgentWorkQueue
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


def test_overlapping_cycles_can_claim_a_message_only_once(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1)])
    queue_a = AgentWorkQueue(store)
    queue_b = AgentWorkQueue(store)
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(queue: AgentWorkQueue) -> None:
        barrier.wait()
        results.append(len(queue.list_pending("mb-1", 1)))

    threads = [threading.Thread(target=worker, args=(queue_a,)), threading.Thread(target=worker, args=(queue_b,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sorted(results) == [0, 1]
    assert queue_a.pending_count("mb-1") == 0


def test_error_and_stale_running_claims_are_retryable(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1), _message(2)])
    queue = AgentWorkQueue(store)
    claimed = queue.list_pending("mb-1", 2)
    assert len(claimed) == 2

    store.record_agent_processing("mb-1", "remote-1", status="error", error="temporary")
    retry = queue.list_pending("mb-1", 1)
    assert [item["remote_id"] for item in retry] == ["remote-1"]

    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE agent_processing SET processed_at=? WHERE message_id='remote-2'", (old,))
    stale_retry = queue.list_pending("mb-1", 2)
    assert "remote-2" in {item["remote_id"] for item in stale_retry}
