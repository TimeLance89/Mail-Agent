from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one old block, found {count}")
    return text.replace(old, new, 1)


path = "apps/gateway/mail_agent_gateway/conversation_store.py"
text = read(path)

text = replace_once(
    text,
    '                "SELECT status, waiting_since, snoozed_until, followup_draft_id FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",',
    '                "SELECT status, waiting_since, snoozed_until, followup_draft_id, last_message_id FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",',
    "load existing conversation state",
)

old_state = '''            waiting_since = (\n                existing["waiting_since"]\n                if existing and existing["status"] == status.value and existing["waiting_since"]\n                else now.isoformat() if status in {ConversationStatus.TO_REPLY, ConversationStatus.AWAITING_REPLY} else None\n            )\n            due_at = _add_business_days(_parse_dt(waiting_since) or now, due_days)\n            snoozed_until = existing["snoozed_until"] if existing else None\n            followup_draft_id = existing["followup_draft_id"] if existing else None\n'''
new_state = '''            same_message_state = bool(\n                existing\n                and existing["status"] == status.value\n                and str(existing["last_message_id"] or "") == message.message_id\n            )\n            waiting_since = (\n                existing["waiting_since"]\n                if same_message_state and existing["waiting_since"]\n                else now.isoformat() if status in {ConversationStatus.TO_REPLY, ConversationStatus.AWAITING_REPLY} else None\n            )\n            due_at = _add_business_days(_parse_dt(waiting_since) or now, due_days)\n            # A new incoming message is new work: an old snooze or follow-up draft must never hide it.\n            snoozed_until = existing["snoozed_until"] if same_message_state else None\n            followup_draft_id = (\n                existing["followup_draft_id"]\n                if same_message_state and status == ConversationStatus.AWAITING_REPLY\n                else None\n            )\n'''
text = replace_once(text, old_state, new_state, "new message clears stale snooze/followup")

old_upsert = '''                    followup_draft_id=CASE\n                        WHEN excluded.status='awaiting_reply' THEN conversation_threads.followup_draft_id\n                        ELSE NULL\n                    END,\n'''
new_upsert = '''                    followup_draft_id=excluded.followup_draft_id,\n'''
text = replace_once(text, old_upsert, new_upsert, "followup draft authoritative upsert")

old_outbound = '''        now = datetime.now(UTC)\n        due_at = _add_business_days(now, awaiting_reply_days)\n        with self._lock, self._connect() as conn:\n            conn.execute(\n'''
new_outbound = '''        now = datetime.now(UTC)\n        due_at = _add_business_days(now, awaiting_reply_days)\n        with self._lock, self._connect() as conn:\n            existing = conn.execute(\n                "SELECT * FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",\n                (mailbox_id, thread_id),\n            ).fetchone()\n            # Approval execution is idempotent. Replaying an already-sent approval must not\n            # restart the waiting clock and silently postpone its follow-up deadline.\n            if (\n                existing\n                and existing["status"] == ConversationStatus.AWAITING_REPLY.value\n                and str(existing["last_message_id"] or "") == str(source_message_id or "")\n            ):\n                return self._thread_row(existing)\n            conn.execute(\n'''
text = replace_once(text, old_outbound, new_outbound, "idempotent outbound conversation clock")
write(path, text)


test_path = "tests/test_conversation_intelligence.py"
test = read(test_path)
if "test_new_message_clears_old_snooze_and_followup_draft" not in test:
    if "import time\n" not in test:
        test = test.replace("from datetime import UTC, datetime, timedelta\n", "from datetime import UTC, datetime, timedelta\nimport time\n")
    test += '''\n\ndef test_new_message_clears_old_snooze_and_followup_draft(tmp_path):\n    store = ConversationStore(tmp_path / "conversation.db")\n    store.record_analysis(\n        message=message("m2"),\n        proposal=proposal(status=ConversationStatus.AWAITING_REPLY),\n        decision_path=[],\n        to_reply_days=2,\n        awaiting_reply_days=4,\n    )\n    store.mark_followup_draft("mb", "t1", "dr1")\n    store.snooze("mb", "t1", (datetime.now(UTC) + timedelta(days=3)).isoformat())\n\n    item = store.record_analysis(\n        message=message("m3"),\n        proposal=proposal(status=ConversationStatus.TO_REPLY),\n        decision_path=[],\n        to_reply_days=2,\n        awaiting_reply_days=4,\n    )\n\n    assert item["last_message_id"] == "m3"\n    assert item["status"] == "to_reply"\n    assert item["snoozed_until"] is None\n    assert item["followup_draft_id"] is None\n\n\ndef test_duplicate_outbound_execution_does_not_restart_followup_clock(tmp_path):\n    store = ConversationStore(tmp_path / "conversation.db")\n    store.record_analysis(\n        message=message("m2"),\n        proposal=proposal(),\n        decision_path=[],\n        to_reply_days=2,\n        awaiting_reply_days=4,\n    )\n    first = store.mark_outbound_sent(\n        mailbox_id="mb",\n        thread_id="t1",\n        source_message_id="m2",\n        recipient="person@company.example",\n        subject="Re: Subject",\n        awaiting_reply_days=4,\n    )\n    time.sleep(0.01)\n    second = store.mark_outbound_sent(\n        mailbox_id="mb",\n        thread_id="t1",\n        source_message_id="m2",\n        recipient="person@company.example",\n        subject="Re: Subject",\n        awaiting_reply_days=4,\n    )\n\n    assert second["waiting_since"] == first["waiting_since"]\n    assert second["due_at"] == first["due_at"]\n'''
    write(test_path, test)
