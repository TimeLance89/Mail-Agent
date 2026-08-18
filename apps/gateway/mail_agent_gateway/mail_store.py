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
                    last_error TEXT
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
                    decided_by TEXT
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
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_drafts_mailbox
                    ON drafts(mailbox_id, created_at DESC);
                """
            )

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
            )
            for item in messages
        ]
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO messages (
                    mailbox_id, uid, internet_message_id, thread_key, sender,
                    recipients_json, subject, sent_at, body_text, seen, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, uid) DO UPDATE SET
                    internet_message_id=excluded.internet_message_id,
                    thread_key=excluded.thread_key,
                    sender=excluded.sender,
                    recipients_json=excluded.recipients_json,
                    subject=excluded.subject,
                    sent_at=excluded.sent_at,
                    body_text=excluded.body_text,
                    seen=excluded.seen,
                    synced_at=excluded.synced_at
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
                       recipients_json, subject, sent_at, body_text, seen, synced_at
                FROM messages WHERE mailbox_id=? ORDER BY uid DESC LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["recipients"] = json.loads(item.pop("recipients_json"))
            item["seen"] = bool(item["seen"])
            result.append(item)
        return result

    def get_last_uid(self, mailbox_id: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT last_uid FROM sync_state WHERE mailbox_id=?",
                (mailbox_id,),
            ).fetchone()
        return int(row["last_uid"]) if row else 0

    def record_sync(self, mailbox_id: str, *, last_uid: int, error: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (mailbox_id, last_uid, last_synced_at, last_error)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mailbox_id) DO UPDATE SET
                    last_uid=excluded.last_uid,
                    last_synced_at=excluded.last_synced_at,
                    last_error=excluded.last_error
                """,
                (mailbox_id, last_uid, utc_now(), error),
            )

    def sync_status(self, mailbox_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT mailbox_id, last_uid, last_synced_at, last_error FROM sync_state WHERE mailbox_id=?",
                (mailbox_id,),
            ).fetchone()
        return dict(row) if row else {
            "mailbox_id": mailbox_id,
            "last_uid": 0,
            "last_synced_at": None,
            "last_error": None,
        }

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
                    proposal_json, policy_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
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
        return {
            "approval_id": approval_id,
            "status": "pending",
            "created_at": created_at,
            "proposal": json.loads(proposal_json),
            "policy": json.loads(policy_json),
        }

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
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drafts (
                    draft_id, mailbox_id, message_id, thread_id, recipient, subject,
                    body, source_action, approval_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        return {
            "draft_id": draft_id,
            "mailbox_id": proposal.mailbox_id,
            "message_id": proposal.message_id,
            "thread_id": proposal.thread_id,
            "recipient": proposal.recipient,
            "subject": proposal.subject,
            "body": proposal.body,
            "source_action": proposal.action.value,
            "approval_id": approval_id,
            "status": status,
            "created_at": created_at,
        }

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
        return [dict(row) for row in rows]

    def list_approvals(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        return [self._approval_row(row) for row in rows]

    def decide_approval(self, approval_id: str, *, decision: str, actor: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Unsupported approval decision")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "pending":
                raise RuntimeError("Approval has already been decided")
            decided_at = utc_now()
            conn.execute(
                """
                UPDATE approvals SET status=?, decided_at=?, decided_by=?
                WHERE approval_id=? AND status='pending'
                """,
                (decision, decided_at, actor, approval_id),
            )
            updated = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
        return self._approval_row(updated)

    @staticmethod
    def _approval_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["proposal"] = json.loads(data.pop("proposal_json"))
        data["policy"] = json.loads(data.pop("policy_json"))
        return data
