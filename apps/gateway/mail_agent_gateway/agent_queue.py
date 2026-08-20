from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .mail_store import MailStore

_ALLOWED_PROCESSING_TABLES = {"agent_processing", "agent_shadow_processing"}
_STALE_CLAIM_MINUTES = 15


class AgentWorkQueue:
    """Durable work queue with atomic claim-before-analysis semantics.

    Live and Shadow processing use separate durable processing tables. `list_pending` atomically
    moves selected rows to `running` before returning them. Overlapping sync/manual cycles therefore
    cannot send the same message to the LLM twice. Abandoned claims are retried after a conservative
    stale window, which is safely above the provider timeout.
    """

    def __init__(self, mail_store: MailStore, *, processing_table: str = "agent_processing"):
        if processing_table not in _ALLOWED_PROCESSING_TABLES:
            raise ValueError("Unsupported agent processing table")
        self.mail_store = mail_store
        self.processing_table = processing_table

    @staticmethod
    def _message_id(item: Any) -> str:
        return str(item["remote_id"] or item["internet_message_id"] or item["uid"])

    def list_pending(self, mailbox_id: str, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        table = self.processing_table
        now = datetime.now(UTC)
        stale_before = (now - timedelta(minutes=_STALE_CLAIM_MINUTES)).isoformat()
        now_text = now.isoformat()

        with self.mail_store._lock, self.mail_store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"""
                UPDATE {table}
                   SET status='error', error='Recovered stale running claim', processed_at=?
                 WHERE mailbox_id=? AND status='running' AND processed_at<?
                """,
                (now_text, mailbox_id, stale_before),
            )
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
            for row in rows:
                message_id = self._message_id(row)
                conn.execute(
                    f"""
                    INSERT INTO {table} (
                        mailbox_id, message_id, status, proposal_action, confidence, processed_at, error
                    ) VALUES (?, ?, 'running', NULL, NULL, ?, NULL)
                    ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                        status='running', proposal_action=NULL, confidence=NULL,
                        processed_at=excluded.processed_at, error=NULL
                    """,
                    (mailbox_id, message_id, now_text),
                )
            conn.commit()
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
                  AND (p.status IS NULL OR p.status IN ('error', 'running'))
                """,
                (mailbox_id,),
            ).fetchone()
        return int(row["count"] if row else 0)
