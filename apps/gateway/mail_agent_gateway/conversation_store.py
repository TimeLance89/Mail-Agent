from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mail_agent_core.agent import MailMessageContext
from mail_agent_core.models import ConversationStatus, MailActionProposal


_PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "yahoo.com", "yahoo.de", "gmx.de", "gmx.net",
    "web.de", "t-online.de", "mailbox.org", "fastmail.com",
}
_PATTERN_CATEGORIES = {"newsletter", "advertising", "cold_outreach", "notification", "finance", "support"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _add_business_days(start: datetime, days: int | None) -> str | None:
    if days is None:
        return None
    days = max(1, int(days))
    cursor = start
    remaining = days
    while remaining:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor.isoformat()


def _sender_address(value: str) -> str:
    raw = (value or "").strip().lower()
    if "<" in raw and ">" in raw:
        raw = raw.split("<", 1)[1].split(">", 1)[0].strip()
    return raw


class ConversationStore:
    """Durable local state for conversation-level intelligence.

    This store contains derived workflow state only. It is never an authority boundary: mailbox
    mutation, outbound sending and approval continue to be enforced by the existing Policy Engine
    and deterministic executor.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_threads (
                    mailbox_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    last_message_id TEXT,
                    last_sender TEXT,
                    subject TEXT NOT NULL DEFAULT '',
                    waiting_since TEXT,
                    due_at TEXT,
                    snoozed_until TEXT,
                    followup_draft_id TEXT,
                    decision_json TEXT NOT NULL DEFAULT '[]',
                    coalesced_count INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (mailbox_id, thread_id)
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_status
                    ON conversation_threads(mailbox_id, status, due_at, updated_at DESC);

                CREATE TABLE IF NOT EXISTS sender_observations (
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    category TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (mailbox_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sender_observations_sender
                    ON sender_observations(mailbox_id, sender, observed_at DESC);

                CREATE TABLE IF NOT EXISTS sender_pattern_decisions (
                    mailbox_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    PRIMARY KEY (mailbox_id, sender, category)
                );

                CREATE TABLE IF NOT EXISTS undo_actions (
                    token TEXT PRIMARY KEY,
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT,
                    thread_id TEXT,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_undo_available
                    ON undo_actions(status, expires_at DESC);
                """
            )

    @staticmethod
    def thread_id(message: MailMessageContext) -> str:
        return (message.thread_id or message.message_id).strip()

    def record_analysis(
        self,
        *,
        message: MailMessageContext,
        proposal: MailActionProposal,
        decision_path: list[dict[str, Any]],
        to_reply_days: int | None,
        awaiting_reply_days: int | None,
        coalesced_count: int = 1,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        thread_id = self.thread_id(message)
        status = proposal.conversation_status
        if status is None:
            status = ConversationStatus.TO_REPLY if proposal.needs_reply else ConversationStatus.FYI
        due_days = to_reply_days if status == ConversationStatus.TO_REPLY else awaiting_reply_days if status == ConversationStatus.AWAITING_REPLY else None
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT status, waiting_since, snoozed_until, followup_draft_id, last_message_id FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",
                (message.mailbox_id, thread_id),
            ).fetchone()
            same_message_state = bool(
                existing
                and existing["status"] == status.value
                and str(existing["last_message_id"] or "") == message.message_id
            )
            waiting_since = (
                existing["waiting_since"]
                if same_message_state and existing["waiting_since"]
                else now.isoformat() if status in {ConversationStatus.TO_REPLY, ConversationStatus.AWAITING_REPLY} else None
            )
            due_at = _add_business_days(_parse_dt(waiting_since) or now, due_days)
            # A new incoming message is new work: an old snooze or follow-up draft must never hide it.
            snoozed_until = existing["snoozed_until"] if same_message_state else None
            followup_draft_id = (
                existing["followup_draft_id"]
                if same_message_state and status == ConversationStatus.AWAITING_REPLY
                else None
            )
            conn.execute(
                """
                INSERT INTO conversation_threads (
                    mailbox_id, thread_id, status, rationale, last_message_id, last_sender,
                    subject, waiting_since, due_at, snoozed_until, followup_draft_id,
                    decision_json, coalesced_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, thread_id) DO UPDATE SET
                    status=excluded.status,
                    rationale=excluded.rationale,
                    last_message_id=excluded.last_message_id,
                    last_sender=excluded.last_sender,
                    subject=excluded.subject,
                    waiting_since=excluded.waiting_since,
                    due_at=excluded.due_at,
                    snoozed_until=excluded.snoozed_until,
                    followup_draft_id=excluded.followup_draft_id,
                    decision_json=excluded.decision_json,
                    coalesced_count=excluded.coalesced_count,
                    updated_at=excluded.updated_at
                """,
                (
                    message.mailbox_id,
                    thread_id,
                    status.value,
                    proposal.conversation_rationale or proposal.reason or "",
                    message.message_id,
                    message.sender,
                    message.subject,
                    waiting_since,
                    due_at,
                    snoozed_until,
                    followup_draft_id,
                    json.dumps(decision_path, ensure_ascii=False),
                    max(1, int(coalesced_count)),
                    now.isoformat(),
                ),
            )
        return self.get_thread(message.mailbox_id, thread_id)

    def mark_outbound_sent(
        self,
        *,
        mailbox_id: str,
        thread_id: str,
        source_message_id: str | None,
        recipient: str,
        subject: str,
        awaiting_reply_days: int | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        due_at = _add_business_days(now, awaiting_reply_days)
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",
                (mailbox_id, thread_id),
            ).fetchone()
            # Approval execution is idempotent. Replaying an already-sent approval must not
            # restart the waiting clock and silently postpone its follow-up deadline.
            if (
                existing
                and existing["status"] == ConversationStatus.AWAITING_REPLY.value
                and str(existing["last_message_id"] or "") == str(source_message_id or "")
            ):
                return self._thread_row(existing)
            conn.execute(
                """
                INSERT INTO conversation_threads (
                    mailbox_id, thread_id, status, rationale, last_message_id, last_sender,
                    subject, waiting_since, due_at, decision_json, coalesced_count, updated_at
                ) VALUES (?, ?, 'awaiting_reply', ?, ?, ?, ?, ?, ?, '[]', 1, ?)
                ON CONFLICT(mailbox_id, thread_id) DO UPDATE SET
                    status='awaiting_reply',
                    rationale=excluded.rationale,
                    last_message_id=COALESCE(excluded.last_message_id, conversation_threads.last_message_id),
                    last_sender=excluded.last_sender,
                    subject=excluded.subject,
                    waiting_since=excluded.waiting_since,
                    due_at=excluded.due_at,
                    snoozed_until=NULL,
                    followup_draft_id=NULL,
                    updated_at=excluded.updated_at
                """,
                (
                    mailbox_id,
                    thread_id,
                    "MAIL-AGENT hat eine freigegebene Antwort gesendet; die Gegenseite ist jetzt am Zug.",
                    source_message_id,
                    recipient,
                    subject,
                    now.isoformat(),
                    due_at,
                    now.isoformat(),
                ),
            )
        return self.get_thread(mailbox_id, thread_id)

    def get_thread(self, mailbox_id: str, thread_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversation_threads WHERE mailbox_id=? AND thread_id=?",
                (mailbox_id, thread_id),
            ).fetchone()
        if row is None:
            raise KeyError(thread_id)
        return self._thread_row(row)

    @staticmethod
    def _thread_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["decision_path"] = json.loads(item.pop("decision_json") or "[]")
        except json.JSONDecodeError:
            item["decision_path"] = []
            item.pop("decision_json", None)
        return item

    def list_threads(
        self,
        *,
        mailbox_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        include_snoozed: bool = False,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        where: list[str] = []
        params: list[Any] = []
        if mailbox_id:
            where.append("mailbox_id=?")
            params.append(mailbox_id)
        if status:
            where.append("status=?")
            params.append(status)
        if not include_snoozed:
            where.append("(snoozed_until IS NULL OR snoozed_until<=?)")
            params.append(utc_now())
        sql = "SELECT * FROM conversation_threads"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE status WHEN 'to_reply' THEN 0 WHEN 'awaiting_reply' THEN 1 WHEN 'fyi' THEN 2 ELSE 3 END, COALESCE(due_at, updated_at) ASC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._thread_row(row) for row in rows]

    def snooze(self, mailbox_id: str, thread_id: str, until: str | None) -> dict[str, Any]:
        parsed = _parse_dt(until) if until else None
        if until and (parsed is None or parsed <= datetime.now(UTC)):
            raise ValueError("Snooze-Zeitpunkt muss in der Zukunft liegen")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_threads SET snoozed_until=?, updated_at=? WHERE mailbox_id=? AND thread_id=?",
                (parsed.isoformat() if parsed else None, utc_now(), mailbox_id, thread_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(thread_id)
        return self.get_thread(mailbox_id, thread_id)

    def due_followups(self, mailbox_id: str, limit: int = 50) -> list[dict[str, Any]]:
        now = utc_now()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversation_threads
                WHERE mailbox_id=?
                  AND status IN ('to_reply','awaiting_reply')
                  AND due_at IS NOT NULL AND due_at<=?
                  AND (snoozed_until IS NULL OR snoozed_until<=?)
                ORDER BY due_at ASC LIMIT ?
                """,
                (mailbox_id, now, now, max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._thread_row(row) for row in rows]

    def mark_followup_draft(self, mailbox_id: str, thread_id: str, draft_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE conversation_threads SET followup_draft_id=?, updated_at=? WHERE mailbox_id=? AND thread_id=?",
                (draft_id, utc_now(), mailbox_id, thread_id),
            )

    def record_sender_observation(
        self,
        *,
        mailbox_id: str,
        message_id: str,
        sender: str,
        category: str,
        min_samples: int,
        confidence_threshold: float,
    ) -> dict[str, Any] | None:
        normalized = _sender_address(sender)
        if not normalized or "@" not in normalized or category not in _PATTERN_CATEGORIES:
            return None
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO sender_observations (mailbox_id, message_id, sender, category, observed_at) VALUES (?, ?, ?, ?, ?)",
                (mailbox_id, message_id, normalized, category, utc_now()),
            )
            if cursor.rowcount == 0:
                return None
            rows = conn.execute(
                "SELECT category, COUNT(*) AS count FROM sender_observations WHERE mailbox_id=? AND sender=? GROUP BY category ORDER BY count DESC",
                (mailbox_id, normalized),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) AS count FROM sender_observations WHERE mailbox_id=? AND sender=?",
                (mailbox_id, normalized),
            ).fetchone()
            decision = conn.execute(
                "SELECT status FROM sender_pattern_decisions WHERE mailbox_id=? AND sender=? AND category=?",
                (mailbox_id, normalized, category),
            ).fetchone()
        total = int(total_row["count"] if total_row else 0)
        if not rows or total < max(3, int(min_samples)):
            return None
        top_category = str(rows[0]["category"])
        top_count = int(rows[0]["count"])
        confidence = top_count / total if total else 0.0
        domain = normalized.rsplit("@", 1)[-1]
        if domain in _PUBLIC_EMAIL_DOMAINS or top_category != category or confidence < float(confidence_threshold):
            return None
        if decision and decision["status"] in {"accepted", "rejected"}:
            return None
        return {
            "mailbox_id": mailbox_id,
            "sender": normalized,
            "category": top_category,
            "samples": total,
            "matching_samples": top_count,
            "confidence": round(confidence, 4),
            "status": "open",
        }

    def list_pattern_suggestions(
        self,
        *,
        mailbox_id: str | None = None,
        min_samples: int = 6,
        confidence_threshold: float = 0.9,
    ) -> list[dict[str, Any]]:
        where = "WHERE mailbox_id=?" if mailbox_id else ""
        params: tuple[Any, ...] = (mailbox_id,) if mailbox_id else ()
        with self._lock, self._connect() as conn:
            senders = conn.execute(
                f"SELECT DISTINCT mailbox_id, sender FROM sender_observations {where}", params
            ).fetchall()
            result: list[dict[str, Any]] = []
            for sender_row in senders:
                mb = str(sender_row["mailbox_id"])
                sender = str(sender_row["sender"])
                domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
                if domain in _PUBLIC_EMAIL_DOMAINS:
                    continue
                categories = conn.execute(
                    "SELECT category, COUNT(*) AS count FROM sender_observations WHERE mailbox_id=? AND sender=? GROUP BY category ORDER BY count DESC",
                    (mb, sender),
                ).fetchall()
                total = sum(int(item["count"]) for item in categories)
                if not categories or total < max(3, int(min_samples)):
                    continue
                category = str(categories[0]["category"])
                count = int(categories[0]["count"])
                confidence = count / total if total else 0
                if category not in _PATTERN_CATEGORIES or confidence < confidence_threshold:
                    continue
                decision = conn.execute(
                    "SELECT status FROM sender_pattern_decisions WHERE mailbox_id=? AND sender=? AND category=?",
                    (mb, sender, category),
                ).fetchone()
                if decision and decision["status"] in {"accepted", "rejected"}:
                    continue
                result.append({
                    "mailbox_id": mb,
                    "sender": sender,
                    "category": category,
                    "samples": total,
                    "matching_samples": count,
                    "confidence": round(confidence, 4),
                    "status": "open",
                })
        return sorted(result, key=lambda item: (-item["confidence"], -item["samples"], item["sender"]))

    def decide_pattern(self, mailbox_id: str, sender: str, category: str, *, status: str) -> None:
        if status not in {"accepted", "rejected"}:
            raise ValueError("Unsupported sender pattern decision")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sender_pattern_decisions (mailbox_id, sender, category, status, decided_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, sender, category) DO UPDATE SET status=excluded.status, decided_at=excluded.decided_at
                """,
                (mailbox_id, _sender_address(sender), category, status, utc_now()),
            )

    def create_undo(
        self,
        *,
        mailbox_id: str,
        message_id: str | None,
        thread_id: str | None,
        action: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> dict[str, Any]:
        ttl_seconds = max(5, min(int(ttl_seconds), 120))
        now = datetime.now(UTC)
        token = "undo_" + uuid.uuid4().hex
        expires = now + timedelta(seconds=ttl_seconds)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO undo_actions (token, mailbox_id, message_id, thread_id, action, payload_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (token, mailbox_id, message_id, thread_id, action, json.dumps(payload, ensure_ascii=False), now.isoformat(), expires.isoformat()),
            )
        return {"token": token, "action": action, "expires_at": expires.isoformat(), "status": "available"}

    def list_available_undo(self, limit: int = 10) -> list[dict[str, Any]]:
        now = utc_now()
        limit = max(1, min(int(limit), 50))
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE undo_actions SET status='expired' WHERE status='available' AND expires_at<=?",
                (now,),
            )
            rows = conn.execute(
                """
                SELECT token, mailbox_id, message_id, thread_id, action, created_at, expires_at, status
                FROM undo_actions
                WHERE status='available' AND expires_at>?
                ORDER BY created_at DESC LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_undo(self, token: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM undo_actions WHERE token=?", (token,)).fetchone()
        if row is None:
            raise KeyError(token)
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        if item["status"] == "available" and (_parse_dt(item["expires_at"]) or datetime.min.replace(tzinfo=UTC)) < datetime.now(UTC):
            item["status"] = "expired"
        return item

    def complete_undo(self, token: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE undo_actions SET status='completed', completed_at=? WHERE token=? AND status='available'",
                (utc_now(), token),
            )
