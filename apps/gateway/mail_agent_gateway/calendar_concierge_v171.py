from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .calendar_concierge import CalendarConciergeRequest
from .calendar_concierge_v17 import ReliableCalendarConcierge
from .calendar_reliable import CalendarFreeSlotRequest, ReliableCalendarProposalRequest
from .calendar_service import (
    CalendarAction,
    CalendarEventDraft,
    CalendarFreeBusyRequest,
    CalendarProposal,
)

_DMY_DATE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_TIME_COLON = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_TIME_UHR = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*Uhr\b", re.IGNORECASE)
_CREATE_INTENT = re.compile(
    r"\b(erstelle|erstell|anlegen|lege\s+.*\s+an|eintragen|trag\s+.*\s+ein|"
    r"plane\s+(diesen|den)\s+termin|übernimm\s+.*\s+kalender|buche)\b",
    re.IGNORECASE,
)

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _extract_explicit_datetime(text: str, zone: ZoneInfo) -> datetime | None:
    value = str(text or "")
    dates: list[tuple[int, int, int]] = []
    for match in _DMY_DATE.finditer(value):
        dates.append((int(match.group(3)), int(match.group(2)), int(match.group(1))))
    for match in _ISO_DATE.finditer(value):
        dates.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    dates = list(dict.fromkeys(dates))

    times: list[tuple[int, int]] = []
    for match in _TIME_COLON.finditer(value):
        times.append((int(match.group(1)), int(match.group(2))))
    for match in _TIME_UHR.finditer(value):
        candidate = (int(match.group(1)), 0)
        if candidate not in times:
            times.append(candidate)
    times = list(dict.fromkeys(times))

    if len(dates) != 1 or len(times) != 1:
        return None
    year, month, day = dates[0]
    hour, minute = times[0]
    try:
        return datetime(year, month, day, hour, minute, tzinfo=zone)
    except ValueError:
        return None


def _event_time(event: dict[str, Any], key: str) -> datetime | None:
    value = event.get(key) or {}
    raw = value.get("dateTime") if isinstance(value, dict) else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class TargetedCalendarConcierge(ReliableCalendarConcierge):
    """0.17.1: exact mail times are checked before generic slot discovery.

    A concrete date/time from owner input or untrusted mail is a factual scheduling candidate,
    never an authorization. The gateway checks that exact interval directly with Google Free/Busy,
    including weekends. Generic working-hour slots are used only as alternatives.
    """

    async def _target_check(
        self,
        request: CalendarConciergeRequest,
        *,
        source_mail: dict[str, Any] | None,
        calendar_meta: dict[str, Any],
    ) -> dict[str, Any] | None:
        zone_name = request.time_zone or str(calendar_meta.get("timeZone") or calendar_meta.get("time_zone") or "UTC")
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
            zone_name = "UTC"

        owner_target = _extract_explicit_datetime(request.instruction, zone)
        source_text = ""
        if source_mail:
            source_text = f"{source_mail.get('subject') or ''}\n{source_mail.get('body') or ''}"
        mail_target = _extract_explicit_datetime(source_text, zone)
        target = owner_target or mail_target
        if target is None:
            return None

        end = target + timedelta(minutes=request.duration_minutes)
        payload = await self.calendar_service.freebusy(
            CalendarFreeBusyRequest(
                mailbox_id=request.mailbox_id,
                time_min=target.isoformat(),
                time_max=end.isoformat(),
                calendar_ids=[request.calendar_id],
                time_zone=zone_name,
            )
        )
        busy = [
            item
            for calendar in (payload.get("calendars") or {}).values()
            for item in (calendar.get("busy") or [])
        ]
        conflicts: list[dict[str, Any]] = []
        if busy:
            events = await self.calendar_service.events(
                request.mailbox_id,
                calendar_id=request.calendar_id,
                time_min=target.isoformat(),
                time_max=end.isoformat(),
                max_results=50,
            )
            for event in events:
                event_start = _event_time(event, "start")
                event_end = _event_time(event, "end")
                if event_start and event_end and target < event_end.astimezone(zone) and end > event_start.astimezone(zone):
                    conflicts.append(
                        {
                            "id": event.get("id"),
                            "summary": event.get("summary") or "Belegter Termin",
                            "start": event_start.isoformat(),
                            "end": event_end.isoformat(),
                        }
                    )

        alternatives: list[dict[str, Any]] = []
        if busy:
            day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            slots = await self.calendar_service.find_free_slots(
                CalendarFreeSlotRequest(
                    mailbox_id=request.mailbox_id,
                    calendar_ids=[request.calendar_id],
                    time_min=day_start.isoformat(),
                    time_max=day_end.isoformat(),
                    duration_minutes=request.duration_minutes,
                    workday_start=request.workday_start,
                    workday_end=request.workday_end,
                    weekdays=[target.weekday()],
                    time_zone=zone_name,
                    max_results=50,
                )
            )
            candidates = list(slots.get("slots") or [])
            candidates.sort(
                key=lambda item: abs(
                    datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00")).astimezone(zone) - target
                )
            )
            selected: list[datetime] = []
            for item in candidates:
                start = datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00")).astimezone(zone)
                if all(abs(start - other) >= timedelta(minutes=request.duration_minutes) for other in selected):
                    alternatives.append(item)
                    selected.append(start)
                if len(alternatives) >= 3:
                    break

        return {
            "source": "owner_instruction" if owner_target else "source_mail",
            "start": target.isoformat(),
            "end": end.isoformat(),
            "time_zone": zone_name,
            "is_free": not busy,
            "conflicts": conflicts,
            "alternatives": alternatives,
        }

    @staticmethod
    def _answer_for_target(check: dict[str, Any], *, language: str) -> str:
        start = datetime.fromisoformat(check["start"])
        end = datetime.fromisoformat(check["end"])
        weekdays = _WEEKDAYS_EN if language == "en" else _WEEKDAYS_DE
        weekday = weekdays[start.weekday()]
        if language == "en":
            when = f"{weekday}, {start:%Y-%m-%d at %H:%M}–{end:%H:%M}"
            if check["is_free"]:
                return f"The requested time on {when} is free in your calendar."
            conflict = check.get("conflicts") or []
            detail = f" It conflicts with {conflict[0]['summary']}." if conflict else ""
            return f"The requested time on {when} is busy.{detail}"
        when = f"{weekday}, {start:%d.%m.%Y} von {start:%H:%M} bis {end:%H:%M} Uhr"
        if check["is_free"]:
            return f"Der angefragte Termin am {when} ist in deinem Kalender frei."
        conflict = check.get("conflicts") or []
        detail = f" Er kollidiert mit „{conflict[0]['summary']}“." if conflict else ""
        alternatives = check.get("alternatives") or []
        if alternatives:
            labels = [datetime.fromisoformat(item["start"]).strftime("%H:%M") for item in alternatives]
            return f"Der angefragte Termin am {when} ist belegt.{detail} Am selben Tag wären stattdessen {', '.join(labels)} Uhr frei."
        return f"Der angefragte Termin am {when} ist belegt.{detail}"

    async def assist(self, request: CalendarConciergeRequest) -> dict[str, Any]:
        calendars = await self.calendar_service.calendars(request.mailbox_id)
        calendar_meta = next(
            (item for item in calendars if str(item.get("id")) == request.calendar_id),
            next((item for item in calendars if item.get("primary")), {}),
        )
        source_mail = self._source_mail(request.mailbox_id, request.source_message_id)
        check = await self._target_check(
            request,
            source_mail=source_mail,
            calendar_meta=calendar_meta,
        )
        if check is None:
            return await super().assist(request)

        profile = self._profile()
        trusted_create = bool(_CREATE_INTENT.search(request.instruction))
        if trusted_create:
            if not check["is_free"] and not request.allow_conflict:
                answer = self._answer_for_target(check, language=profile.language)
                return {
                    "kind": "clarification",
                    "answer": answer + (" Erlaube den Konflikt ausdrücklich oder wähle eine Alternative." if profile.language != "en" else " Explicitly allow the conflict or choose an alternative."),
                    "requested_time_check": check,
                    "free_slots": check.get("alternatives") or [],
                }
            summary = str((source_mail or {}).get("subject") or "Termin").strip() or "Termin"
            proposal = CalendarProposal(
                action=CalendarAction.CREATE,
                mailbox_id=request.mailbox_id,
                calendar_id=request.calendar_id,
                event=CalendarEventDraft(
                    summary=summary[:500],
                    start=check["start"],
                    end=check["end"],
                    time_zone=check["time_zone"],
                ),
                send_updates="none",
                reason="Owner explicitly requested the concrete mail appointment to be added",
                source_message_id=request.source_message_id,
            )
            approval = await self.calendar_service.propose_checked(
                ReliableCalendarProposalRequest(
                    proposal=proposal,
                    actor=request.actor,
                    allow_conflict=request.allow_conflict,
                )
            )
            return {
                "kind": "proposal",
                "answer": self._answer_for_target(check, language=profile.language) + (" Der Kalendereintrag ist vorbereitet und wartet auf deine Freigabe." if profile.language != "en" else " The calendar entry is prepared and awaits your approval."),
                "proposal": proposal.model_dump(mode="json"),
                "approval": approval,
                "requested_time_check": check,
                "free_slots": check.get("alternatives") or [],
            }

        answer = self._answer_for_target(check, language=profile.language)
        self.audit_log.append(
            "calendar_exact_time_checked",
            actor=request.actor,
            details={
                "mailbox_id": request.mailbox_id,
                "calendar_id": request.calendar_id,
                "source": check["source"],
                "is_free": check["is_free"],
                "source_message": bool(request.source_message_id),
            },
        )
        return {
            "kind": "answer",
            "answer": answer,
            "requested_time_check": check,
            "free_slots": check.get("alternatives") or [],
        }
