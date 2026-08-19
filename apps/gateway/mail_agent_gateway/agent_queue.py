from __future__ import annotations

from typing import Any

from .mail_store import MailStore

_ALLOWED_PROCESSING_TABLES = {"agent_processing", "agent_shadow_processing"}


class AgentWorkQueue:
    """Select unprocessed mail before applying the per-cycle limit.

    Live and Shadow processing use separate durable processing tables. This is critical: a
    side-effect-free Shadow run must never consume the production queue, otherwise switching
    back to Live mode could incorrectly skip mail that was only simulated.
    """

    def __init__(self, mail_store: MailStore, *, processing_table: str = "agent_processing"):
        if processing_table not in _ALLOWED_PROCESSING_TABLES:
            raise ValueError("Unsupported agent processing table")
        self.mail_store = mail_store
        self.processing_table = processing_table

    def list_pending(self, mailbox_id: str, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        table = self.processing_table
        with self.mail_store._lock, self.mail_store._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.mailbox_id, m.uid, m.internet_message_id, m.thread_key, m.sender,
                       m.recipients_json, m.subject, m.sent_at, m.body_text, m.seen, m.synced_at,
                       m.remote_id, m.remote_thread_id, m.connector, m.agent_priority, m.agent_category,
                       m.agent_summary, m.needs_reply, m.analyzed_at
                FROM messages AS m
                LEFT JOIN {table} AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                ORDER BY CASE WHEN p.status IS NULL THEN 0 ELSE 1 END ASC, m.uid DESC
                LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
        return [self.mail_store._message_row(row) for row in rows]

    def pending_count(self, mailbox_id: str) -> int:
        table = self.processing_table
        with self.mail_store._lock, self.mail_store._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM messages AS m
                LEFT JOIN {table} AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                """,
                (mailbox_id,),
            ).fetchone()
        return int(row["count"] if row else 0)
