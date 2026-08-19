from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mail_agent_core.models import MailActionProposal, PolicyDecision


_EXECUTABLE_ACTIONS = {
    "mark_read",
    "move",
    "archive",
    "delete",
    "send_reply",
    "forward",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class StoredMessage:
    mailbox_id: str
    uid: int
    internet_message_id: str | None
    thread_key: str
    sender: str
    recipients: list[str]
    subject: str
    sent_at: str | None
    body_text: str
    seen: bool
    remote_id: str | None = None
    remote_thread_id: str | None = None
    connector: str = "imap"


class MailStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    mailbox_id TEXT NOT NULL,
                    uid INTEGER NOT NULL,
                    internet_message_id TEXT,
                    thread_key TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    recipients_json TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    sent_at TEXT,
                    body_text TEXT NOT NULL,
                    seen INTEGER NOT NULL DEFAULT 0,
                    synced_at TEXT NOT NULL,
                    remote_id TEXT,
                    remote_thread_id TEXT,
                    connector TEXT NOT NULL DEFAULT 'imap',
                    agent_priority TEXT,
                    agent_category TEXT,
                    agent_summary TEXT,
                    needs_reply INTEGER,
                    analyzed_at TEXT,
                    PRIMARY KEY (mailbox_id, uid)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_thread
                    ON messages(mailbox_id, thread_key, uid DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_synced
                    ON messages(mailbox_id, uid DESC);

                CREATE TABLE IF NOT EXISTS sync_state (
                    mailbox_id TEXT PRIMARY KEY,
                    last_uid INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT,
                    last_error TEXT,
                    cursor TEXT
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT,
                    thread_id TEXT,
                    action TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    execution_status TEXT NOT NULL DEFAULT 'not_applicable',
                    execution_started_at TEXT,
                    executed_at TEXT,
                    execution_result_json TEXT,
                    execution_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status
                    ON approvals(status, created_at DESC);

                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT,
                    thread_id TEXT,
                    recipient TEXT,
                    subject TEXT,
                    body TEXT NOT NULL,
                    source_action TEXT NOT NULL,
                    approval_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    proposal_json TEXT,
                    updated_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    edited_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_drafts_mailbox
                    ON drafts(mailbox_id, created_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_remote
                    ON messages(mailbox_id, remote_id) WHERE remote_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS agent_processing (
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_action TEXT,
                    confidence REAL,
                    processed_at TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (mailbox_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_processing_time
                    ON agent_processing(mailbox_id, processed_at DESC);

                CREATE TABLE IF NOT EXISTS agent_shadow_processing (
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_action TEXT,
                    confidence REAL,
                    processed_at TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (mailbox_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_shadow_processing_time
                    ON agent_shadow_processing(mailbox_id, processed_at DESC);
                """
            )
            self._ensure_column(conn, "messages", "remote_id", "TEXT")
            self._ensure_column(conn, "messages", "remote_thread_id", "TEXT")
            self._ensure_column(conn, "messages", "connector", "TEXT NOT NULL DEFAULT 'imap'")
            self._ensure_column(conn, "messages", "agent_priority", "TEXT")
            self._ensure_column(conn, "messages", "agent_category", "TEXT")
            self._ensure_column(conn, "messages", "agent_summary", "TEXT")
            self._ensure_column(conn, "messages", "needs_reply", "INTEGER")
            self._ensure_column(conn, "messages", "analyzed_at", "TEXT")
            self._ensure_column(conn, "sync_state", "cursor", "TEXT")
            self._ensure_column(conn, "approvals", "execution_status", "TEXT NOT NULL DEFAULT 'not_applicable'")
            self._ensure_column(conn, "approvals", "execution_started_at", "TEXT")
            self._ensure_column(conn, "approvals", "executed_at", "TEXT")
            self._ensure_column(conn, "approvals", "execution_result_json", "TEXT")
            self._ensure_column(conn, "approvals", "execution_error", "TEXT")
            self._ensure_column(conn, "drafts", "proposal_json", "TEXT")
            self._ensure_column(conn, "drafts", "updated_at", "TEXT")
            self._ensure_column(conn, "drafts", "revision", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "drafts", "edited_by", "TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_remote "
                "ON messages(mailbox_id, remote_id) WHERE remote_id IS NOT NULL"
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _message_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["recipients"] = json.loads(item.pop("recipients_json"))
        item["seen"] = bool(item["seen"])
        if item.get("needs_reply") is not None:
            item["needs_reply"] = bool(item["needs_reply"])
        return item

    def upsert_messages(self, messages: list[StoredMessage]) -> int:
        if not messages:
            return 0
        now = utc_now()
        rows = [
            (
                item.mailbox_id,
                item.uid,
                item.internet_message_id,
                item.thread_key,
                item.sender,
                json.dumps(item.recipients, ensure_ascii=False),
                item.subject,
                item.sent_at,
                item.body_text,
                1 if item.seen else 0,
                now,
                item.remote_id,
                item.remote_thread_id,
                item.connector,
            )
            for item in messages
        ]
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO messages (
                    mailbox_id, uid, internet_message_id, thread_key, sender,
                    recipients_json, subject, sent_at, body_text, seen, synced_at,
                    remote_id, remote_thread_id, connector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, uid) DO UPDATE SET
                    internet_message_id=excluded.internet_message_id,
                    thread_key=excluded.thread_key,
                    sender=excluded.sender,
                    recipients_json=excluded.recipients_json,
                    subject=excluded.subject,
                    sent_at=excluded.sent_at,
                    body_text=excluded.body_text,
                    seen=excluded.seen,
                    synced_at=excluded.synced_at,
                    remote_id=excluded.remote_id,
                    remote_thread_id=excluded.remote_thread_id,
                    connector=excluded.connector
                """,
                rows,
            )
        return len(messages)

    def list_messages(self, mailbox_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mailbox_id, uid, internet_message_id, thread_key, sender,
                       recipients_json, subject, sent_at, body_text, seen, synced_at,
                       remote_id, remote_thread_id, connector, agent_priority, agent_category,
                       agent_summary, needs_reply, analyzed_at
                FROM messages WHERE mailbox_id=? ORDER BY uid DESC LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def get_message(self, mailbox_id: str, message_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT mailbox_id, uid, internet_message_id, thread_key, sender,
                       recipients_json, subject, sent_at, body_text, seen, synced_at,
                       remote_id, remote_thread_id, connector, agent_priority, agent_category,
                       agent_summary, needs_reply, analyzed_at
                FROM messages
                WHERE mailbox_id=? AND (
                    remote_id=? OR internet_message_id=? OR CAST(uid AS TEXT)=?
                )
                LIMIT 1
                """,
                (mailbox_id, message_id, message_id, message_id),
            ).fetchone()
        return self._message_row(row) if row else None

    def list_thread_messages(
        self,
        mailbox_id: str,
        thread_key: str,
        *,
        limit: int = 8,
        exclude_message_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 30))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mailbox_id, uid, internet_message_id, thread_key, sender,
                       recipients_json, subject, sent_at, body_text, seen, synced_at,
                       remote_id, remote_thread_id, connector, agent_priority, agent_category,
                       agent_summary, needs_reply, analyzed_at
                FROM messages
                WHERE mailbox_id=? AND thread_key=?
                ORDER BY uid DESC LIMIT ?
                """,
                (mailbox_id, thread_key, limit + 1),
            ).fetchall()
        items = [self._message_row(row) for row in reversed(rows)]
        if exclude_message_id is not None:
            items = [
                item for item in items
                if str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid")) != exclude_message_id
            ]
        return items[-limit:]

    def update_message_intelligence(
        self,
        mailbox_id: str,
        message_id: str,
        *,
        priority: str,
        category: str,
        summary: str,
        needs_reply: bool,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE messages
                SET agent_priority=?, agent_category=?, agent_summary=?, needs_reply=?, analyzed_at=?
                WHERE mailbox_id=? AND (
                    remote_id=? OR internet_message_id=? OR CAST(uid AS TEXT)=?
                )
                """,
                (
                    priority,
                    category,
                    summary,
                    1 if needs_reply else 0,
                    utc_now(),
                    mailbox_id,
                    message_id,
                    message_id,
                    message_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_seen(self, mailbox_id: str, message_id: str, *, seen: bool = True) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE messages SET seen=?
                WHERE mailbox_id=? AND (remote_id=? OR internet_message_id=? OR CAST(uid AS TEXT)=?)
                """,
                (1 if seen else 0, mailbox_id, message_id, message_id, message_id),
            )
            return cursor.rowcount > 0

    def remove_message(self, mailbox_id: str, message_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM messages
                WHERE mailbox_id=? AND (remote_id=? OR internet_message_id=? OR CAST(uid AS TEXT)=?)
                """,
                (mailbox_id, message_id, message_id, message_id),
            )
            return cursor.rowcount > 0

    def get_last_uid(self, mailbox_id: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT last_uid FROM sync_state WHERE mailbox_id=?",
                (mailbox_id,),
            ).fetchone()
        return int(row["last_uid"]) if row else 0

    def record_sync(
        self,
        mailbox_id: str,
        *,
        last_uid: int,
        error: str | None = None,
        cursor: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (mailbox_id, last_uid, last_synced_at, last_error, cursor)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id) DO UPDATE SET
                    last_uid=excluded.last_uid,
                    last_synced_at=excluded.last_synced_at,
                    last_error=excluded.last_error,
                    cursor=COALESCE(excluded.cursor, sync_state.cursor)
                """,
                (mailbox_id, last_uid, utc_now(), error, cursor),
            )

    def sync_status(self, mailbox_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT mailbox_id, last_uid, last_synced_at, last_error, cursor FROM sync_state WHERE mailbox_id=?",
                (mailbox_id,),
            ).fetchone()
        return dict(row) if row else {
            "mailbox_id": mailbox_id,
            "last_uid": 0,
            "last_synced_at": None,
            "last_error": None,
            "cursor": None,
        }

    def delete_remote_message(self, mailbox_id: str, remote_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM messages WHERE mailbox_id=? AND remote_id=?",
                (mailbox_id, remote_id),
            )
            return cursor.rowcount > 0

    def clear_messages(self, mailbox_id: str, *, connector: str | None = None) -> int:
        with self._lock, self._connect() as conn:
            if connector:
                cursor = conn.execute(
                    "DELETE FROM messages WHERE mailbox_id=? AND connector=?",
                    (mailbox_id, connector),
                )
            else:
                cursor = conn.execute("DELETE FROM messages WHERE mailbox_id=?", (mailbox_id,))
            return cursor.rowcount

    def is_agent_processed(self, mailbox_id: str, message_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM agent_processing WHERE mailbox_id=? AND message_id=?",
                (mailbox_id, message_id),
            ).fetchone()
        if row is None:
            return False
        return row["status"] != "error"

    def record_agent_processing(
        self,
        mailbox_id: str,
        message_id: str,
        *,
        status: str,
        proposal_action: str | None = None,
        confidence: float | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_processing (
                    mailbox_id, message_id, status, proposal_action, confidence, processed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                    status=excluded.status,
                    proposal_action=excluded.proposal_action,
                    confidence=excluded.confidence,
                    processed_at=excluded.processed_at,
                    error=excluded.error
                """,
                (
                    mailbox_id,
                    message_id,
                    status,
                    proposal_action,
                    confidence,
                    utc_now(),
                    error,
                ),
            )

    def is_shadow_processed(self, mailbox_id: str, message_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM agent_shadow_processing WHERE mailbox_id=? AND message_id=?",
                (mailbox_id, message_id),
            ).fetchone()
        if row is None:
            return False
        return row["status"] != "error"

    def record_shadow_processing(
        self,
        mailbox_id: str,
        message_id: str,
        *,
        status: str,
        proposal_action: str | None = None,
        confidence: float | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_shadow_processing (
                    mailbox_id, message_id, status, proposal_action, confidence, processed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                    status=excluded.status,
                    proposal_action=excluded.proposal_action,
                    confidence=excluded.confidence,
                    processed_at=excluded.processed_at,
                    error=excluded.error
                """,
                (
                    mailbox_id,
                    message_id,
                    status,
                    proposal_action,
                    confidence,
                    utc_now(),
                    error,
                ),
            )

    def enqueue_approval(
        self,
        proposal: MailActionProposal,
        policy: PolicyDecision,
    ) -> dict[str, Any]:
        approval_id = "apr_" + uuid.uuid4().hex
        created_at = utc_now()
        proposal_json = proposal.model_dump_json()
        policy_json = policy.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    approval_id, mailbox_id, message_id, thread_id, action,
                    proposal_json, policy_json, status, created_at, execution_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'not_applicable')
                """,
                (
                    approval_id,
                    proposal.mailbox_id,
                    proposal.message_id,
                    proposal.thread_id,
                    proposal.action.value,
                    proposal_json,
                    policy_json,
                    created_at,
                ),
            )
        return self.get_approval(approval_id)

    def create_draft(
        self,
        proposal: MailActionProposal,
        *,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        if proposal.body is None:
            raise ValueError("Draft proposal does not contain a body")
        draft_id = "dr_" + uuid.uuid4().hex
        created_at = utc_now()
        status = "approval_pending" if approval_id else "draft"
        proposal_json = proposal.model_dump_json()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drafts (
                    draft_id, mailbox_id, message_id, thread_id, recipient, subject,
                    body, source_action, approval_id, status, created_at,
                    proposal_json, updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    draft_id,
                    proposal.mailbox_id,
                    proposal.message_id,
                    proposal.thread_id,
                    proposal.recipient,
                    proposal.subject,
                    proposal.body,
                    proposal.action.value,
                    approval_id,
                    status,
                    created_at,
                    proposal_json,
                    created_at,
                ),
            )
        return self.get_draft(draft_id)

    @staticmethod
    def _draft_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        proposal_json = data.pop("proposal_json", None)
        if proposal_json:
            data["proposal"] = json.loads(proposal_json)
        else:
            data["proposal"] = {
                "action": data["source_action"],
                "mailbox_id": data["mailbox_id"],
                "message_id": data["message_id"],
                "thread_id": data["thread_id"],
                "recipient": data["recipient"],
                "subject": data["subject"],
                "body": data["body"],
            }
        return data

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return self._draft_row(row)

    def list_drafts(self, mailbox_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            if mailbox_id:
                rows = conn.execute(
                    "SELECT * FROM drafts WHERE mailbox_id=? ORDER BY created_at DESC LIMIT ?",
                    (mailbox_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._draft_row(row) for row in rows]

    def update_draft(self, draft_id: str, proposal: MailActionProposal, *, actor: str) -> dict[str, Any]:
        now = utc_now()
        proposal_json = proposal.model_dump_json()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["status"] == "sent":
                raise RuntimeError("Sent drafts cannot be edited")
            if proposal.mailbox_id != row["mailbox_id"] or proposal.message_id != row["message_id"]:
                raise RuntimeError("Draft scope cannot be changed")
            if row["approval_id"]:
                approval = conn.execute(
                    "SELECT status, action FROM approvals WHERE approval_id=?",
                    (row["approval_id"],),
                ).fetchone()
                if approval is None or approval["status"] != "pending":
                    raise RuntimeError("Draft cannot be edited after approval was decided")
                if proposal.action.value != approval["action"]:
                    raise RuntimeError("Draft action cannot change while approval is pending")
                conn.execute(
                    "UPDATE approvals SET proposal_json=? WHERE approval_id=?",
                    (proposal_json, row["approval_id"]),
                )
            conn.execute(
                """
                UPDATE drafts
                SET recipient=?, subject=?, body=?, source_action=?, proposal_json=?,
                    updated_at=?, revision=revision+1, edited_by=?
                WHERE draft_id=?
                """,
                (
                    proposal.recipient,
                    proposal.subject,
                    proposal.body or "",
                    proposal.action.value,
                    proposal_json,
                    now,
                    actor,
                    draft_id,
                ),
            )
        return self.get_draft(draft_id)

    def link_draft_approval(self, draft_id: str, approval_id: str, *, source_action: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT status, approval_id FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
            if row is None:
                raise KeyError(draft_id)
            if row["status"] == "sent":
                raise RuntimeError("Sent draft cannot be submitted again")
            if row["approval_id"]:
                raise RuntimeError("Draft already has an approval")
            conn.execute(
                """
                UPDATE drafts
                SET approval_id=?, status='approval_pending', source_action=?, updated_at=?
                WHERE draft_id=?
                """,
                (approval_id, source_action, utc_now(), draft_id),
            )
        return self.get_draft(draft_id)

    def list_approvals(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._approval_row(row) for row in rows]

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return self._approval_row(row)

    def decide_approval(self, approval_id: str, *, decision: str, actor: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Unsupported approval decision")
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "pending":
                raise RuntimeError("Approval has already been decided")
            decided_at = utc_now()
            execution_status = (
                "ready"
                if decision == "approved" and row["action"] in _EXECUTABLE_ACTIONS
                else "not_applicable"
            )
            conn.execute(
                """
                UPDATE approvals
                SET status=?, decided_at=?, decided_by=?, execution_status=?
                WHERE approval_id=? AND status='pending'
                """,
                (decision, decided_at, actor, execution_status, approval_id),
            )
            if decision == "rejected":
                conn.execute(
                    """
                    UPDATE drafts
                    SET status='draft', approval_id=NULL, updated_at=?
                    WHERE approval_id=? AND status='approval_pending'
                    """,
                    (decided_at, approval_id),
                )
            updated = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        return self._approval_row(updated)

    def claim_approval_execution(self, approval_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "approved":
                raise RuntimeError("Approval must be approved before execution")
            if row["execution_status"] in {"sent", "completed"}:
                return self._approval_row(row)
            if row["execution_status"] == "executing":
                raise RuntimeError("Approval execution is already in progress")
            if row["execution_status"] not in {"ready", "failed"}:
                raise RuntimeError("Approval does not represent an executable action")
            started_at = utc_now()
            cursor = conn.execute(
                """
                UPDATE approvals
                SET execution_status='executing', execution_started_at=?, execution_error=NULL
                WHERE approval_id=? AND execution_status IN ('ready', 'failed')
                """,
                (started_at, approval_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Approval execution could not be claimed")
            updated = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        return self._approval_row(updated)

    def complete_approval_execution(
        self,
        approval_id: str,
        result: dict[str, Any],
        *,
        success_status: str = "sent",
    ) -> dict[str, Any]:
        if success_status not in {"sent", "completed"}:
            raise ValueError("Unsupported execution success status")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET execution_status=?, executed_at=?, execution_result_json=?, execution_error=NULL
                WHERE approval_id=? AND execution_status='executing'
                """,
                (success_status, utc_now(), json.dumps(result, ensure_ascii=False), approval_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Approval execution was not in progress")
            if success_status == "sent":
                conn.execute("UPDATE drafts SET status='sent' WHERE approval_id=?", (approval_id,))
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        return self._approval_row(row)

    def fail_approval_execution(self, approval_id: str, error: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET execution_status='failed', execution_error=?
                WHERE approval_id=? AND execution_status='executing'
                """,
                (error[:2000], approval_id),
            )
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return self._approval_row(row)

    @staticmethod
    def _approval_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["proposal"] = json.loads(data.pop("proposal_json"))
        data["policy"] = json.loads(data.pop("policy_json"))
        result_json = data.pop("execution_result_json", None)
        data["execution_result"] = json.loads(result_json) if result_json else None
        return data