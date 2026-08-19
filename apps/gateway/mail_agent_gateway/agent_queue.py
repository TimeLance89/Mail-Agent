from __future__ import annotations

from typing import Any

from .mail_store import MailStore


class AgentWorkQueue:
    """Select unprocessed mail before applying the per-cycle limit.

    The old runtime first limited the newest messages and only then skipped already-processed rows. Once
    those newest rows were processed, older mail could starve forever. This queue filters processing state
    in SQL first, then applies the cycle limit, so every local backlog item eventually gets a turn.
    """

    def __init__(self, mail_store: MailStore):
        self.mail_store = mail_store

    def list_pending(self, mailbox_id: str, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.mail_store._lock, self.mail_store._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.mailbox_id, m.uid, m.internet_message_id, m.thread_key, m.sender,
                       m.recipients_json, m.subject, m.sent_at, m.body_text, m.seen, m.synced_at,
                       m.remote_id, m.remote_thread_id, m.connector, m.agent_priority, m.agent_category,
                       m.agent_summary, m.needs_reply, m.analyzed_at
                FROM messages AS m
                LEFT JOIN agent_processing AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                ORDER BY m.uid DESC
                LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
        return [self.mail_store._message_row(row) for row in rows]

    def pending_count(self, mailbox_id: str) -> int:
        with self.mail_store._lock, self.mail_store._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM messages AS m
                LEFT JOIN agent_processing AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                """,
                (mailbox_id,),
            ).fetchone()
        return int(row["count"] if row else 0)
