from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

from mail_agent_google import CALENDAR_EVENTS_SCOPE, CALENDAR_FREEBUSY_SCOPE

from .calendar_service import (
    CalendarAction,
    CalendarApprovalStore,
    CalendarEventDraft,
    CalendarFreeBusyRequest,
    CalendarProposal,
    CalendarProposalRequest,
    CalendarService,
    _parse_rfc3339,
    utc_now,
)
from .oauth_runtime import current_google_access_token


class CalendarConflictError(RuntimeError):
    def __init__(self, conflicts: list[dict[str, Any]]):
        super().__init__("The requested calendar time conflicts with an existing event")
        self.conflicts = conflicts


class ReliableCalendarProposal(CalendarProposal):
    expected_etag: str | None = Field(default=None, max_length=1024)
    remote_create_id: str | None = Field(default=None, max_length=1024)
    validated_at: str = Field(default_factory=utc_now)
    allow_conflict: bool = False


class ReliableCalendarProposalRequest(BaseModel):
    proposal: CalendarProposal
    actor: str = Field(default="local-user", min_length=1, max_length=200)
    allow_conflict: bool = False


class CalendarFreeSlotRequest(BaseModel):
    mailbox_id: str = Field(min_length=1, max_length=128)
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"], min_length=1, max_length=20)
    time_min: str = Field(min_length=10, max_length=80)
    time_max: str = Field(min_length=10, max_length=80)
    duration_minutes: int = Field(default=30, ge=5, le=8 * 60)
    step_minutes: int = Field(default=15, ge=5, le=120)
    buffer_minutes: int = Field(default=0, ge=0, le=180)
    workday_start: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    workday_end: str = Field(default="18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    time_zone: str | None = Field(default=None, max_length=100)
    max_results: int = Field(default=8, ge=1, le=50)

    @field_validator("calendar_ids")
    @classmethod
    def normalize_calendar_ids(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            calendar_id = str(item or "").strip()
            if calendar_id and calendar_id not in result:
                result.append(calendar_id)
        if not result:
            raise ValueError("at least one calendar is required")
        return result

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, value: list[int]) -> list[int]:
        days = sorted(set(int(item) for item in value))
        if not days or any(item < 0 or item > 6 for item in days):
            raise ValueError("weekdays must contain values 0 through 6")
        return days

    @model_validator(mode="after")
    def validate_range(self):
        if _parse_rfc3339(self.time_max) <= _parse_rfc3339(self.time_min):
            raise ValueError("time_max must be after time_min")
        start_hour, start_minute = (int(part) for part in self.workday_start.split(":"))
        end_hour, end_minute = (int(part) for part in self.workday_end.split(":"))
        if (end_hour, end_minute) <= (start_hour, start_minute):
            raise ValueError("workday_end must be after workday_start")
        return self


class ReliableCalendarApprovalStore(CalendarApprovalStore):
    def recover_stale_executions(self) -> int:
        """Make orphaned executions retryable after a process restart.

        Create uses a deterministic Google event id; update/delete use ETag reconciliation. Therefore a
        retry is safe and cannot silently duplicate a calendar mutation.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE calendar_approvals
                   SET execution_status='failed',
                       execution_error='Execution was interrupted; safe retry is available'
                 WHERE execution_status='executing'
                """
            )
            return int(cursor.rowcount)


class ReliableGoogleCalendarClient:
    """Google Calendar client with event reads and optimistic concurrency support."""

    def __init__(self, access_token: str, *, timeout: float = 25.0):
        from mail_agent_google import GoogleCalendarClient

        self._client = GoogleCalendarClient(access_token, timeout=timeout)
        self.access_token = access_token
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _calendar_path(calendar_id: str) -> str:
        from urllib.parse import quote

        return quote(str(calendar_id or "primary"), safe="")

    async def list_calendars(self, **kwargs):
        return await self._client.list_calendars(**kwargs)

    async def list_events(self, **kwargs):
        return await self._client.list_events(**kwargs)

    async def freebusy(self, **kwargs):
        return await self._client.freebusy(**kwargs)

    async def create_event(self, **kwargs):
        return await self._client.create_event(**kwargs)

    async def get_event(self, *, calendar_id: str, event_id: str) -> dict[str, Any]:
        from urllib.parse import quote

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}"
        )
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        patch: dict[str, Any],
        send_updates: str = "none",
        etag: str | None = None,
    ) -> dict[str, Any]:
        from urllib.parse import quote

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}"
        )
        headers = {"If-Match": etag} if etag else None
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.patch(
                url,
                params={"sendUpdates": send_updates},
                json=patch,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def delete_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        send_updates: str = "none",
        etag: str | None = None,
    ) -> None:
        from urllib.parse import quote

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}"
        )
        headers = {"If-Match": etag} if etag else None
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.delete(
                url,
                params={"sendUpdates": send_updates},
                headers=headers,
            )
            response.raise_for_status()


class ReliableCalendarService(CalendarService):
    async def _client(
        self,
        mailbox_id: str,
        *,
        required_scopes: tuple[str, ...],
    ) -> ReliableGoogleCalendarClient:
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
        return ReliableGoogleCalendarClient(access_token)

    async def _calendar_meta(self, mailbox_id: str, calendar_id: str) -> dict[str, Any]:
        calendars = await self.calendars(mailbox_id)
        if calendar_id == "primary":
            match = next((item for item in calendars if item.get("primary")), None)
        else:
            match = next((item for item in calendars if str(item.get("id")) == calendar_id), None)
        if match is None:
            raise ValueError("Requested calendar is not available on the connected Google account")
        return match

    async def _ensure_writable_calendar(self, mailbox_id: str, calendar_id: str) -> dict[str, Any]:
        meta = await self._calendar_meta(mailbox_id, calendar_id)
        if str(meta.get("access_role") or "").lower() not in {"owner", "writer"}:
            raise PermissionError("The selected Google calendar is read-only")
        return meta

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404

    @staticmethod
    def _event_matches_draft(remote: dict[str, Any], draft: CalendarEventDraft) -> bool:
        expected = draft.google_payload()
        for key in ("summary", "description", "location"):
            if (remote.get(key) or None) != (expected.get(key) or None):
                return False
        if remote.get("start") != expected.get("start") or remote.get("end") != expected.get("end"):
            return False
        remote_attendees = sorted(
            str(item.get("email") or "").casefold()
            for item in remote.get("attendees", [])
            if item.get("email")
        )
        expected_attendees = sorted(item["email"].casefold() for item in expected.get("attendees", []))
        return remote_attendees == expected_attendees

    @staticmethod
    def _remote_create_id(approval_id: str) -> str:
        # Google custom event ids accept lower-case base32hex characters. Hex is a safe subset.
        digest = hashlib.sha256(approval_id.encode("utf-8")).hexdigest()[:40]
        return f"ma{digest}"

    async def _current_event(
        self,
        mailbox_id: str,
        *,
        calendar_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        client = await self._client(mailbox_id, required_scopes=(CALENDAR_EVENTS_SCOPE,))
        return await client.get_event(calendar_id=calendar_id, event_id=event_id)

    async def conflicts_for_event(
        self,
        mailbox_id: str,
        *,
        calendar_id: str,
        event: CalendarEventDraft,
        exclude_event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        client = await self._client(mailbox_id, required_scopes=(CALENDAR_EVENTS_SCOPE,))
        items = await client.list_events(
            calendar_id=calendar_id,
            time_min=event.start,
            time_max=event.end,
            max_results=50,
        )
        conflicts: list[dict[str, Any]] = []
        for item in items:
            event_id = str(item.get("id") or "")
            if not event_id or event_id == str(exclude_event_id or ""):
                continue
            if item.get("status") == "cancelled" or item.get("transparency") == "transparent":
                continue
            conflicts.append(
                {
                    "id": event_id,
                    "summary": item.get("summary") or "(ohne Titel)",
                    "start": item.get("start"),
                    "end": item.get("end"),
                }
            )
        return conflicts

    async def propose_checked(
        self,
        request: ReliableCalendarProposalRequest | CalendarProposalRequest,
    ) -> dict[str, Any]:
        proposal = request.proposal
        mailbox = self._mailbox(proposal.mailbox_id)
        if not self._calendar_enabled(mailbox):
            raise PermissionError("Google Calendar is not connected with write permissions")
        await self._ensure_writable_calendar(proposal.mailbox_id, proposal.calendar_id)

        allow_conflict = bool(getattr(request, "allow_conflict", False))
        expected_etag: str | None = None
        if proposal.action in {CalendarAction.UPDATE, CalendarAction.DELETE}:
            if not proposal.event_id:
                raise ValueError("Calendar mutation requires an existing event id")
            remote = await self._current_event(
                proposal.mailbox_id,
                calendar_id=proposal.calendar_id,
                event_id=proposal.event_id,
            )
            expected_etag = str(remote.get("etag") or "") or None
        if proposal.action in {CalendarAction.CREATE, CalendarAction.UPDATE}:
            assert proposal.event is not None
            conflicts = await self.conflicts_for_event(
                proposal.mailbox_id,
                calendar_id=proposal.calendar_id,
                event=proposal.event,
                exclude_event_id=proposal.event_id,
            )
            if conflicts and not allow_conflict:
                raise CalendarConflictError(conflicts)

        reliable = ReliableCalendarProposal.model_validate(
            {
                **proposal.model_dump(mode="json"),
                "expected_etag": expected_etag,
                "validated_at": utc_now(),
                "allow_conflict": allow_conflict,
            }
        )
        approval = self.store.enqueue(reliable)
        self.audit_log.append(
            "calendar_action_proposed",
            actor=request.actor,
            details={
                "approval_id": approval["approval_id"],
                "mailbox_id": reliable.mailbox_id,
                "action": reliable.action.value,
                "calendar_id": reliable.calendar_id,
                "event_id": reliable.event_id,
                "conflict_override": reliable.allow_conflict,
                "attendee_count": len(reliable.event.attendees) if reliable.event else 0,
                "send_updates": reliable.send_updates,
            },
        )
        return approval

    async def find_free_slots(self, request: CalendarFreeSlotRequest) -> dict[str, Any]:
        start = _parse_rfc3339(request.time_min)
        end = _parse_rfc3339(request.time_max)
        meta = await self._calendar_meta(request.mailbox_id, request.calendar_ids[0])
        zone_name = request.time_zone or str(meta.get("time_zone") or "UTC")
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown calendar timezone: {zone_name}") from exc

        payload = await self.freebusy(
            CalendarFreeBusyRequest(
                mailbox_id=request.mailbox_id,
                time_min=request.time_min,
                time_max=request.time_max,
                calendar_ids=request.calendar_ids,
                time_zone=zone_name,
            )
        )
        buffer = timedelta(minutes=request.buffer_minutes)
        busy: list[tuple[datetime, datetime]] = []
        for calendar in payload.get("calendars", {}).values():
            for interval in calendar.get("busy", []):
                busy_start = _parse_rfc3339(interval["start"]) - buffer
                busy_end = _parse_rfc3339(interval["end"]) + buffer
                busy.append((busy_start.astimezone(UTC), busy_end.astimezone(UTC)))
        busy.sort(key=lambda item: item[0])

        local_start = start.astimezone(zone)
        local_end = end.astimezone(zone)
        start_hour, start_minute = (int(part) for part in request.workday_start.split(":"))
        end_hour, end_minute = (int(part) for part in request.workday_end.split(":"))
        duration = timedelta(minutes=request.duration_minutes)
        step = timedelta(minutes=request.step_minutes)
        slots: list[dict[str, Any]] = []

        day = local_start.date()
        while day <= local_end.date() and len(slots) < request.max_results:
            if day.weekday() in request.weekdays:
                day_start = datetime.combine(day, time(start_hour, start_minute), tzinfo=zone)
                day_end = datetime.combine(day, time(end_hour, end_minute), tzinfo=zone)
                cursor = max(day_start, local_start)
                minute_mod = cursor.minute % request.step_minutes
                if minute_mod or cursor.second or cursor.microsecond:
                    cursor = cursor.replace(second=0, microsecond=0) + timedelta(
                        minutes=(request.step_minutes - minute_mod) % request.step_minutes
                    )
                while cursor + duration <= min(day_end, local_end):
                    candidate_end = cursor + duration
                    cand_start_utc = cursor.astimezone(UTC)
                    cand_end_utc = candidate_end.astimezone(UTC)
                    if not any(
                        cand_start_utc < busy_end and cand_end_utc > busy_start
                        for busy_start, busy_end in busy
                    ):
                        slots.append(
                            {
                                "start": cursor.isoformat(),
                                "end": candidate_end.isoformat(),
                                "time_zone": zone_name,
                                "duration_minutes": request.duration_minutes,
                            }
                        )
                        if len(slots) >= request.max_results:
                            break
                    cursor += step
            day += timedelta(days=1)

        return {
            "time_min": request.time_min,
            "time_max": request.time_max,
            "time_zone": zone_name,
            "duration_minutes": request.duration_minutes,
            "calendar_ids": request.calendar_ids,
            "slots": slots,
        }

    async def execute(self, approval_id: str) -> dict[str, Any]:
        approval = self.store.claim(approval_id)
        if approval.get("execution_status") == "completed":
            return approval
        proposal = ReliableCalendarProposal.model_validate(approval["proposal"])
        try:
            client = await self._client(
                proposal.mailbox_id,
                required_scopes=(CALENDAR_EVENTS_SCOPE,),
            )
            await self._ensure_writable_calendar(proposal.mailbox_id, proposal.calendar_id)

            if proposal.action in {CalendarAction.CREATE, CalendarAction.UPDATE}:
                assert proposal.event is not None
                conflicts = await self.conflicts_for_event(
                    proposal.mailbox_id,
                    calendar_id=proposal.calendar_id,
                    event=proposal.event,
                    exclude_event_id=proposal.event_id,
                )
                if conflicts and not proposal.allow_conflict:
                    raise CalendarConflictError(conflicts)

            if proposal.action == CalendarAction.CREATE:
                assert proposal.event is not None
                remote_id = proposal.remote_create_id or self._remote_create_id(approval_id)
                try:
                    existing = await client.get_event(
                        calendar_id=proposal.calendar_id,
                        event_id=remote_id,
                    )
                except Exception as exc:
                    if not self._is_not_found(exc):
                        raise
                    existing = None
                if existing is not None:
                    marker = (
                        existing.get("extendedProperties", {})
                        .get("private", {})
                        .get("mailAgentApprovalId")
                    )
                    if marker != approval_id or not self._event_matches_draft(existing, proposal.event):
                        raise RuntimeError("Deterministic calendar event id is already occupied")
                    remote = existing
                    reconciled = True
                else:
                    payload = proposal.event.google_payload()
                    payload["id"] = remote_id
                    payload["extendedProperties"] = {
                        "private": {"mailAgentApprovalId": approval_id}
                    }
                    try:
                        remote = await client.create_event(
                            calendar_id=proposal.calendar_id,
                            event=payload,
                            send_updates=proposal.send_updates,
                        )
                        reconciled = False
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 409:
                            raise
                        remote = await client.get_event(
                            calendar_id=proposal.calendar_id,
                            event_id=remote_id,
                        )
                        marker = (
                            remote.get("extendedProperties", {})
                            .get("private", {})
                            .get("mailAgentApprovalId")
                        )
                        if marker != approval_id or not self._event_matches_draft(remote, proposal.event):
                            raise RuntimeError("Google reported an unrelated event id collision") from exc
                        reconciled = True
                result = {
                    "connector": "google_calendar",
                    "action": "create",
                    "calendar_id": proposal.calendar_id,
                    "event_id": remote.get("id") or remote_id,
                    "status": remote.get("status"),
                    "html_link": remote.get("htmlLink"),
                    "reconciled": reconciled,
                }
            elif proposal.action == CalendarAction.UPDATE:
                assert proposal.event is not None and proposal.event_id is not None
                current = await client.get_event(
                    calendar_id=proposal.calendar_id,
                    event_id=proposal.event_id,
                )
                current_etag = str(current.get("etag") or "") or None
                if proposal.expected_etag and current_etag != proposal.expected_etag:
                    if self._event_matches_draft(current, proposal.event):
                        remote = current
                        reconciled = True
                    else:
                        raise RuntimeError(
                            "Calendar event changed after approval was prepared; refresh and re-approve"
                        )
                else:
                    remote = await client.update_event(
                        calendar_id=proposal.calendar_id,
                        event_id=proposal.event_id,
                        patch=proposal.event.google_payload(),
                        send_updates=proposal.send_updates,
                        etag=current_etag,
                    )
                    reconciled = False
                result = {
                    "connector": "google_calendar",
                    "action": "update",
                    "calendar_id": proposal.calendar_id,
                    "event_id": remote.get("id") or proposal.event_id,
                    "status": remote.get("status"),
                    "html_link": remote.get("htmlLink"),
                    "reconciled": reconciled,
                }
            else:
                assert proposal.event_id is not None
                try:
                    current = await client.get_event(
                        calendar_id=proposal.calendar_id,
                        event_id=proposal.event_id,
                    )
                except Exception as exc:
                    if not self._is_not_found(exc):
                        raise
                    current = None
                if current is None:
                    reconciled = True
                else:
                    current_etag = str(current.get("etag") or "") or None
                    if proposal.expected_etag and current_etag != proposal.expected_etag:
                        raise RuntimeError(
                            "Calendar event changed after approval was prepared; refresh and re-approve"
                        )
                    await client.delete_event(
                        calendar_id=proposal.calendar_id,
                        event_id=proposal.event_id,
                        send_updates=proposal.send_updates,
                        etag=current_etag,
                    )
                    reconciled = False
                result = {
                    "connector": "google_calendar",
                    "action": "delete",
                    "calendar_id": proposal.calendar_id,
                    "event_id": proposal.event_id,
                    "status": "deleted",
                    "reconciled": reconciled,
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
                    "reconciled": result.get("reconciled", False),
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
