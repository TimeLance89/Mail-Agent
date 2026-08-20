from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from mail_agent_google import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_FREEBUSY_SCOPE,
    CALENDAR_LIST_SCOPE,
    GOOGLE_CALENDAR_SCOPES,
    GoogleCalendarClient,
)
from pydantic import BaseModel, Field, field_validator, model_validator

from .audit import AuditLog
from .oauth_runtime import current_google_access_token
from .vault import CredentialVault

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_rfc3339(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("timestamp is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must contain an explicit timezone offset")
    return parsed


def _scope_set(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").replace(",", " ").split() if item.strip()}


class CalendarAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class CalendarEventDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    start: str = Field(min_length=10, max_length=80)
    end: str = Field(min_length=10, max_length=80)
    description: str | None = Field(default=None, max_length=20_000)
    location: str | None = Field(default=None, max_length=1000)
    attendees: list[str] = Field(default_factory=list, max_length=100)
    time_zone: str | None = Field(default=None, max_length=100)

    @field_validator("attendees")
    @classmethod
    def validate_attendees(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            email = str(item or "").strip().lower()
            if not email:
                continue
            if not _EMAIL_RE.match(email):
                raise ValueError(f"invalid attendee email: {email}")
            if email not in normalized:
                normalized.append(email)
        return normalized

    @model_validator(mode="after")
    def validate_time_range(self):
        start = _parse_rfc3339(self.start)
        end = _parse_rfc3339(self.end)
        if end <= start:
            raise ValueError("event end must be after event start")
        return self

    def google_payload(self) -> dict[str, Any]:
        start: dict[str, str] = {"dateTime": self.start}
        end: dict[str, str] = {"dateTime": self.end}
        if self.time_zone:
            start["timeZone"] = self.time_zone
            end["timeZone"] = self.time_zone
        payload: dict[str, Any] = {
            "summary": self.summary,
            "start": start,
            "end": end,
        }
        if self.description:
            payload["description"] = self.description
        if self.location:
            payload["location"] = self.location
        if self.attendees:
            payload["attendees"] = [{"email": email} for email in self.attendees]
        return payload


class CalendarProposal(BaseModel):
    action: CalendarAction
    mailbox_id: str = Field(min_length=1, max_length=128)
    calendar_id: str = Field(default="primary", min_length=1, max_length=1024)
    event_id: str | None = Field(default=None, max_length=1024)
    event: CalendarEventDraft | None = None
    send_updates: Literal["none", "all"] = "none"
    reason: str = Field(default="", max_length=2000)
    source_message_id: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.action == CalendarAction.CREATE and self.event is None:
            raise ValueError("create proposal requires event details")
        if self.action == CalendarAction.UPDATE and (not self.event_id or self.event is None):
            raise ValueError("update proposal requires event_id and event details")
        if self.action == CalendarAction.DELETE and not self.event_id:
            raise ValueError("delete proposal requires event_id")
        return self


class CalendarProposalRequest(BaseModel):
    proposal: CalendarProposal
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class CalendarFreeBusyRequest(BaseModel):
    mailbox_id: str = Field(min_length=1, max_length=128)
    time_min: str = Field(min_length=10, max_length=80)
    time_max: str = Field(min_length=10, max_length=80)
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"], min_length=1, max_length=50)
    time_zone: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_range(self):
        if _parse_rfc3339(self.time_max) <= _parse_rfc3339(self.time_min):
            raise ValueError("time_max must be after time_min")
        return self


class CalendarApprovalStore:
    """Separate approval queue for Calendar mutations.

    Calendar writes never reuse mailbox approval rows. This keeps mail execution invariants intact
    while still providing the same atomic claim -> execute -> complete lifecycle.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS calendar_approvals (
                    approval_id TEXT PRIMARY KEY,
                    mailbox_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
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
                CREATE INDEX IF NOT EXISTS idx_calendar_approvals_status
                    ON calendar_approvals(status, created_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["proposal"] = json.loads(data.pop("proposal_json"))
        result = data.pop("execution_result_json", None)
        data["execution_result"] = json.loads(result) if result else None
        data["policy"] = {
            "allowed": True,
            "requires_approval": True,
            "risk": "high",
            "reason": "Calendar mutations always require explicit owner approval",
        }
        return data

    def enqueue(self, proposal: CalendarProposal) -> dict[str, Any]:
        approval_id = "calapr_" + uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calendar_approvals(
                    approval_id, mailbox_id, action, proposal_json, status, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (
                    approval_id,
                    proposal.mailbox_id,
                    proposal.action.value,
                    proposal.model_dump_json(),
                    utc_now(),
                ),
            )
        return self.get(approval_id)

    def get(self, approval_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return self._row(row)

    def list(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM calendar_approvals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._row(row) for row in rows]

    def decide(self, approval_id: str, *, decision: str, actor: str) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Unsupported calendar approval decision")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "pending":
                raise RuntimeError("Calendar approval has already been decided")
            execution_status = "ready" if decision == "approved" else "not_applicable"
            conn.execute(
                """
                UPDATE calendar_approvals
                SET status=?, decided_at=?, decided_by=?, execution_status=?
                WHERE approval_id=? AND status='pending'
                """,
                (decision, utc_now(), actor, execution_status, approval_id),
            )
        return self.get(approval_id)

    def claim(self, approval_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "approved":
                raise RuntimeError("Calendar approval must be approved before execution")
            if row["execution_status"] == "completed":
                return self._row(row)
            if row["execution_status"] == "executing":
                raise RuntimeError("Calendar approval execution is already in progress")
            if row["execution_status"] not in {"ready", "failed"}:
                raise RuntimeError("Calendar approval is not executable")
            cursor = conn.execute(
                """
                UPDATE calendar_approvals
                SET execution_status='executing', execution_started_at=?, execution_error=NULL
                WHERE approval_id=? AND execution_status IN ('ready', 'failed')
                """,
                (utc_now(), approval_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Calendar approval execution could not be claimed")
        return self.get(approval_id)

    def complete(self, approval_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE calendar_approvals
                SET execution_status='completed', executed_at=?, execution_result_json=?,
                    execution_error=NULL
                WHERE approval_id=? AND execution_status='executing'
                """,
                (utc_now(), json.dumps(result, ensure_ascii=False), approval_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Calendar approval execution was not in progress")
        return self.get(approval_id)

    def fail(self, approval_id: str, error: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE calendar_approvals
                SET execution_status='failed', execution_error=?
                WHERE approval_id=? AND execution_status='executing'
                """,
                (str(error)[:2000], approval_id),
            )
        return self.get(approval_id)


class CalendarService:
    def __init__(
        self,
        *,
        store: CalendarApprovalStore,
        mailbox_lookup: Callable[[str], dict[str, Any]],
        mailbox_supplier: Callable[[], list[dict[str, Any]]],
        vault: CredentialVault,
        google_client_id: str,
        google_client_secret: str | None,
        audit_log: AuditLog,
    ) -> None:
        self.store = store
        self.mailbox_lookup = mailbox_lookup
        self.mailbox_supplier = mailbox_supplier
        self.vault = vault
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.audit_log = audit_log

    @staticmethod
    def _calendar_scopes(mailbox: dict[str, Any]) -> set[str]:
        return _scope_set(mailbox.get("scope"))

    @classmethod
    def _calendar_enabled(cls, mailbox: dict[str, Any]) -> bool:
        return all(scope in cls._calendar_scopes(mailbox) for scope in GOOGLE_CALENDAR_SCOPES)

    def status(self) -> dict[str, Any]:
        accounts: list[dict[str, Any]] = []
        for mailbox in self.mailbox_supplier():
            if mailbox.get("oauth_provider") != "google":
                continue
            scopes = self._calendar_scopes(mailbox)
            missing = [scope for scope in GOOGLE_CALENDAR_SCOPES if scope not in scopes]
            accounts.append(
                {
                    "mailbox_id": mailbox.get("mailbox_id"),
                    "email_address": mailbox.get("email_address"),
                    "connected": not missing,
                    "missing_scopes": missing,
                    "capabilities": list(mailbox.get("capabilities") or ["mail"]),
                }
            )
        return {
            "supported": bool(self.google_client_id),
            "accounts": accounts,
            "write_requires_approval": True,
            "direct_write_allowed": False,
            "scopes": list(GOOGLE_CALENDAR_SCOPES),
        }

    def _mailbox(self, mailbox_id: str) -> dict[str, Any]:
        mailbox = self.mailbox_lookup(mailbox_id)
        if mailbox.get("oauth_provider") != "google" or mailbox.get("connector") != "gmail_api":
            raise RuntimeError("Calendar currently requires a connected Google account")
        return mailbox

    async def _client(
        self,
        mailbox_id: str,
        *,
        required_scopes: tuple[str, ...],
    ) -> GoogleCalendarClient:
        mailbox = self._mailbox(mailbox_id)
        scopes = self._calendar_scopes(mailbox)
        missing = [scope for scope in required_scopes if scope not in scopes]
        if missing:
            raise PermissionError("Google Calendar is not connected with the required permissions")
        access_token = await current_google_access_token(
            mailbox,
            vault=self.vault,
            client_id=self.google_client_id,
            client_secret=self.google_client_secret,
        )
        return GoogleCalendarClient(access_token)

    async def calendars(self, mailbox_id: str) -> list[dict[str, Any]]:
        client = await self._client(mailbox_id, required_scopes=(CALENDAR_LIST_SCOPE,))
        items = await client.list_calendars()
        return [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "primary": bool(item.get("primary")),
                "access_role": item.get("accessRole"),
                "time_zone": item.get("timeZone"),
                "selected": item.get("selected", True),
            }
            for item in items
        ]

    async def events(
        self,
        mailbox_id: str,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        _parse_rfc3339(time_min)
        _parse_rfc3339(time_max)
        client = await self._client(mailbox_id, required_scopes=(CALENDAR_EVENTS_SCOPE,))
        items = await client.list_events(
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        )
        return [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "summary": item.get("summary") or "(ohne Titel)",
                "description": item.get("description"),
                "location": item.get("location"),
                "start": item.get("start"),
                "end": item.get("end"),
                "attendees": [
                    {
                        "email": attendee.get("email"),
                        "response_status": attendee.get("responseStatus"),
                        "self": bool(attendee.get("self")),
                    }
                    for attendee in item.get("attendees", [])
                ],
                "html_link": item.get("htmlLink"),
            }
            for item in items
        ]

    async def freebusy(self, request: CalendarFreeBusyRequest) -> dict[str, Any]:
        client = await self._client(request.mailbox_id, required_scopes=(CALENDAR_FREEBUSY_SCOPE,))
        payload = await client.freebusy(
            time_min=request.time_min,
            time_max=request.time_max,
            calendar_ids=request.calendar_ids,
            time_zone=request.time_zone,
        )
        return {
            "time_min": request.time_min,
            "time_max": request.time_max,
            "calendars": payload.get("calendars", {}),
        }

    def propose(self, request: CalendarProposalRequest) -> dict[str, Any]:
        mailbox = self._mailbox(request.proposal.mailbox_id)
        if not self._calendar_enabled(mailbox):
            raise PermissionError("Google Calendar is not connected with write permissions")
        approval = self.store.enqueue(request.proposal)
        self.audit_log.append(
            "calendar_action_proposed",
            actor=request.actor,
            details={
                "approval_id": approval["approval_id"],
                "mailbox_id": request.proposal.mailbox_id,
                "action": request.proposal.action.value,
                "calendar_id": request.proposal.calendar_id,
                "event_id": request.proposal.event_id,
                "attendee_count": len(request.proposal.event.attendees) if request.proposal.event else 0,
                "send_updates": request.proposal.send_updates,
            },
        )
        return approval

    async def approve(self, approval_id: str, *, actor: str) -> dict[str, Any]:
        approval = self.store.decide(approval_id, decision="approved", actor=actor)
        self.audit_log.append(
            "calendar_action_approved",
            actor=actor,
            details={"approval_id": approval_id, "action": approval.get("action")},
        )
        return await self.execute(approval_id)

    def reject(self, approval_id: str, *, actor: str) -> dict[str, Any]:
        approval = self.store.decide(approval_id, decision="rejected", actor=actor)
        self.audit_log.append(
            "calendar_action_rejected",
            actor=actor,
            details={"approval_id": approval_id, "action": approval.get("action")},
        )
        return approval

    async def execute(self, approval_id: str) -> dict[str, Any]:
        approval = self.store.claim(approval_id)
        if approval.get("execution_status") == "completed":
            return approval
        proposal = CalendarProposal.model_validate(approval["proposal"])
        try:
            client = await self._client(
                proposal.mailbox_id,
                required_scopes=(CALENDAR_EVENTS_SCOPE,),
            )
            if proposal.action == CalendarAction.CREATE:
                assert proposal.event is not None
                remote = await client.create_event(
                    calendar_id=proposal.calendar_id,
                    event=proposal.event.google_payload(),
                    send_updates=proposal.send_updates,
                )
                result = {
                    "connector": "google_calendar",
                    "action": "create",
                    "calendar_id": proposal.calendar_id,
                    "event_id": remote.get("id"),
                    "status": remote.get("status"),
                    "html_link": remote.get("htmlLink"),
                }
            elif proposal.action == CalendarAction.UPDATE:
                assert proposal.event is not None and proposal.event_id is not None
                remote = await client.update_event(
                    calendar_id=proposal.calendar_id,
                    event_id=proposal.event_id,
                    patch=proposal.event.google_payload(),
                    send_updates=proposal.send_updates,
                )
                result = {
                    "connector": "google_calendar",
                    "action": "update",
                    "calendar_id": proposal.calendar_id,
                    "event_id": remote.get("id") or proposal.event_id,
                    "status": remote.get("status"),
                    "html_link": remote.get("htmlLink"),
                }
            else:
                assert proposal.event_id is not None
                await client.delete_event(
                    calendar_id=proposal.calendar_id,
                    event_id=proposal.event_id,
                    send_updates=proposal.send_updates,
                )
                result = {
                    "connector": "google_calendar",
                    "action": "delete",
                    "calendar_id": proposal.calendar_id,
                    "event_id": proposal.event_id,
                    "status": "deleted",
                }
            completed = self.store.complete(approval_id, result)
            self.audit_log.append(
                "calendar_action_executed",
                details={
                    "approval_id": approval_id,
                    "mailbox_id": proposal.mailbox_id,
                    "action": proposal.action.value,
                    "calendar_id": proposal.calendar_id,
                    "event_id": result.get("event_id"),
                },
            )
            return completed
        except Exception as exc:
            self.store.fail(approval_id, str(exc))
            self.audit_log.append(
                "calendar_action_execution_failed",
                details={"approval_id": approval_id, "error": str(exc)},
            )
            raise RuntimeError(f"Approved calendar action could not be executed: {exc}") from exc
