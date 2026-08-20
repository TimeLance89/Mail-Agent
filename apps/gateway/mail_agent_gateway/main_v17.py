from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from . import main_v16 as previous
from .calendar_concierge import CalendarConciergeRequest, CalendarMailReplyRequest
from .calendar_concierge_v17 import ReliableCalendarConcierge
from .calendar_mail_intent import calendar_mail_suggestions
from .calendar_reliable import (
    CalendarConflictError,
    CalendarFreeSlotRequest,
    ReliableCalendarApprovalStore,
    ReliableCalendarProposalRequest,
    ReliableCalendarService,
)
from .calendar_service import CalendarFreeBusyRequest
from .schemas import ApprovalDecisionRequest, OAuthStartRequest

APP_VERSION = "0.17.0"
base = previous.base

# 0.17 adds Calendar as a capability on top of the fully verified 0.16.1 runtime. The existing
# mail policy engine, mail approval queue, action executor, identity and adaptive mail reasoning
# remain authoritative and are not widened with Calendar actions.
previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION

calendar_store = ReliableCalendarApprovalStore(base.settings.data_dir / "calendar.db")
recovered_calendar_executions = calendar_store.recover_stale_executions()
calendar_service = ReliableCalendarService(
    store=calendar_store,
    mailbox_lookup=base._mailbox_by_id,
    mailbox_supplier=base._configured_mailboxes,
    vault=base.vault,
    google_client_id=base.settings.google_client_id,
    google_client_secret=base.settings.google_client_secret,
    audit_log=base.audit_log,
)
calendar_concierge = ReliableCalendarConcierge(
    calendar_service=calendar_service,
    model_router=previous.model_router,
    providers=base.providers,
    mail_store=base.mail_store,
    state_store=base.state_store,
    identity_manager=base.identity_manager,
    policy_engine=base.policy_engine,
    audit_log=base.audit_log,
)


def _calendar_http_error(exc: Exception, *, operation: str) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Calendar account, event or source mail not found")
    if isinstance(exc, CalendarConflictError):
        summaries = ", ".join(str(item.get("summary") or item.get("id")) for item in exc.conflicts[:4])
        return HTTPException(
            status_code=409,
            detail=f"Calendar conflict with existing event(s): {summaries or 'occupied time'}",
        )
    if isinstance(exc, (PermissionError, RuntimeError, ValueError)):
        message = str(exc)
        status = 502 if message.startswith("Approved calendar action could not be executed:") else 409
        return HTTPException(status_code=status, detail=message)
    return HTTPException(status_code=502, detail=f"{operation} failed: {exc}")


async def _finish_google_oauth_v17(
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    error_description: str | None,
):
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    try:
        session = base.oauth_controller.sessions.get(state)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="OAuth session not found or expired") from exc
    purpose = session.purpose
    if error:
        message = error_description or error
        base.oauth_controller.fail(state=state, provider="google", error=message)
        title = (
            "Google-Kalender-Verbindung abgebrochen"
            if purpose == "calendar"
            else "Google-Anmeldung abgebrochen"
        )
        return base.HTMLResponse(base._oauth_result_page(False, title, message))
    if not code:
        base.oauth_controller.fail(
            state=state,
            provider="google",
            error="Authorization code is missing",
        )
        title = (
            "Google Kalender konnte nicht verbunden werden"
            if purpose == "calendar"
            else "Google-Anmeldung fehlgeschlagen"
        )
        return base.HTMLResponse(
            base._oauth_result_page(False, title, "Kein Autorisierungscode erhalten.")
        )
    try:
        result = await base.oauth_controller.complete_google(state=state, code=code)
        if result.get("purpose") == "calendar":
            return base.HTMLResponse(
                base._oauth_result_page(
                    True,
                    "Google Kalender ist verbunden",
                    (
                        f"{result.get('email_address') or 'Das Google-Konto'} darf jetzt "
                        "Termine lesen und nach Freigabe verwalten."
                    ),
                )
            )
        return base.HTMLResponse(
            base._oauth_result_page(
                True,
                "Gmail ist verbunden",
                (
                    f"{result.get('email_address') or 'Das Postfach'} wurde sicher mit "
                    "MAIL-AGENT verbunden."
                ),
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="OAuth session not found or expired") from exc
    except Exception as exc:
        title = (
            "Google Kalender konnte nicht verbunden werden"
            if purpose == "calendar"
            else "Google-Anmeldung fehlgeschlagen"
        )
        return base.HTMLResponse(base._oauth_result_page(False, title, str(exc)), status_code=502)


# Existing callback routes resolve this symbol from main.py module globals at request time.
base._finish_google_oauth = _finish_google_oauth_v17


@base.app.post("/v1/oauth/google/calendar/start")
async def start_google_calendar_oauth(body: OAuthStartRequest) -> dict[str, Any]:
    try:
        result = base.oauth_controller.start_google_calendar(body.login_hint)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "provider": result.provider,
        "purpose": "calendar",
        "state": result.state,
        "authorization_url": result.authorization_url,
    }


@base.app.get("/v1/calendar/status")
async def calendar_status() -> dict[str, Any]:
    status = calendar_service.status()
    status["recovered_stale_executions"] = recovered_calendar_executions
    status["features"] = [
        "agenda",
        "free_busy",
        "free_slot_finder",
        "assistant",
        "mail_to_calendar",
        "mail_schedule_detection",
        "availability_reply_draft",
        "approval_gated_mutations",
        "optimistic_concurrency",
        "idempotent_create_retry",
    ]
    return status


@base.app.get("/v1/calendar/calendars")
async def calendar_list(mailbox_id: str) -> dict[str, Any]:
    try:
        return {"calendars": await calendar_service.calendars(mailbox_id)}
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Google Calendar list") from exc


@base.app.get("/v1/calendar/events")
async def calendar_events(
    mailbox_id: str,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    lower = time_min or now.isoformat()
    upper = time_max or (now + timedelta(days=30)).isoformat()
    max_results = max(1, min(int(max_results), 250))
    try:
        events = await calendar_service.events(
            mailbox_id,
            calendar_id=calendar_id,
            time_min=lower,
            time_max=upper,
            max_results=max_results,
        )
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Google Calendar events") from exc
    return {
        "calendar_id": calendar_id,
        "time_min": lower,
        "time_max": upper,
        "events": events,
    }


@base.app.post("/v1/calendar/freebusy")
async def calendar_freebusy(body: CalendarFreeBusyRequest) -> dict[str, Any]:
    try:
        return await calendar_service.freebusy(body)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Google Calendar free/busy") from exc


@base.app.post("/v1/calendar/free-slots")
async def calendar_free_slots(body: CalendarFreeSlotRequest) -> dict[str, Any]:
    try:
        return await calendar_service.find_free_slots(body)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar free-slot search") from exc


@base.app.get("/v1/calendar/briefing")
async def calendar_briefing(
    mailbox_id: str,
    calendar_id: str = "primary",
    duration_minutes: int = 30,
) -> dict[str, Any]:
    duration_minutes = max(5, min(int(duration_minutes), 8 * 60))
    try:
        calendars = await calendar_service.calendars(mailbox_id)
        if calendar_id == "primary":
            meta = next((item for item in calendars if item.get("primary")), None)
        else:
            meta = next((item for item in calendars if str(item.get("id")) == calendar_id), None)
        if meta is None:
            raise ValueError("Requested calendar is not available")
        zone_name = str(meta.get("time_zone") or "UTC")
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
            zone_name = "UTC"
        local_now = datetime.now(UTC).astimezone(zone)
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        events = await calendar_service.events(
            mailbox_id,
            calendar_id=calendar_id,
            time_min=max(local_now, day_start).isoformat(),
            time_max=day_end.isoformat(),
            max_results=100,
        )
        free = await calendar_service.find_free_slots(
            CalendarFreeSlotRequest(
                mailbox_id=mailbox_id,
                calendar_ids=[calendar_id],
                time_min=local_now.isoformat(),
                time_max=(local_now + timedelta(days=7)).isoformat(),
                duration_minutes=duration_minutes,
                time_zone=zone_name,
                max_results=5,
            )
        )
        return {
            "calendar_id": calendar_id,
            "calendar_name": meta.get("summary"),
            "time_zone": zone_name,
            "local_now": local_now.isoformat(),
            "today_events": events,
            "today_count": len(events),
            "next_event": events[0] if events else None,
            "next_free_slots": free.get("slots", []),
        }
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar briefing") from exc


@base.app.get("/v1/calendar/mail-suggestions")
async def calendar_mail_candidates(mailbox_id: str, limit: int = 100) -> dict[str, Any]:
    try:
        base._mailbox_by_id(mailbox_id)
        return {
            "mailbox_id": mailbox_id,
            "suggestions": calendar_mail_suggestions(
                base.mail_store,
                mailbox_id,
                limit=max(1, min(int(limit), 300)),
            ),
            "side_effects": False,
        }
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar mail suggestions") from exc


@base.app.post("/v1/calendar/assist")
@base.app.post("/v1/calendar/concierge")
async def calendar_assist(body: CalendarConciergeRequest) -> dict[str, Any]:
    try:
        return await calendar_concierge.assist(body)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar assistant") from exc


@base.app.post("/v1/calendar/mail-reply")
async def calendar_mail_reply(body: CalendarMailReplyRequest) -> dict[str, Any]:
    try:
        return await calendar_concierge.draft_availability_reply(body)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar availability reply") from exc


@base.app.post("/v1/calendar/proposals")
async def calendar_propose(body: ReliableCalendarProposalRequest) -> dict[str, Any]:
    try:
        return await calendar_service.propose_checked(body)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar proposal") from exc


@base.app.get("/v1/calendar/approvals")
async def calendar_approvals(status: str = "pending", limit: int = 100) -> dict[str, Any]:
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Unsupported calendar approval status")
    return {"approvals": calendar_store.list(status, limit)}


@base.app.get("/v1/calendar/approvals/{approval_id}")
async def calendar_approval(approval_id: str) -> dict[str, Any]:
    try:
        return calendar_store.get(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Calendar approval not found") from exc


@base.app.post("/v1/calendar/approvals/{approval_id}/approve")
async def approve_calendar_action(
    approval_id: str,
    body: ApprovalDecisionRequest,
) -> dict[str, Any]:
    try:
        return await calendar_service.approve(approval_id, actor=body.actor)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Approved Calendar action") from exc


@base.app.post("/v1/calendar/approvals/{approval_id}/execute")
async def retry_calendar_action(approval_id: str) -> dict[str, Any]:
    try:
        return await calendar_service.execute(approval_id)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar retry") from exc


@base.app.post("/v1/calendar/approvals/{approval_id}/reject")
async def reject_calendar_action(
    approval_id: str,
    body: ApprovalDecisionRequest,
) -> dict[str, Any]:
    try:
        return calendar_service.reject(approval_id, actor=body.actor)
    except Exception as exc:
        raise _calendar_http_error(exc, operation="Calendar rejection") from exc


def _move_catch_all_web_mount_to_end() -> None:
    routes = base.app.router.routes
    for index, route in enumerate(routes):
        if getattr(route, "name", None) != "web":
            continue
        if getattr(route, "path", None) not in {"", "/"}:
            continue
        routes.append(routes.pop(index))
        break


_move_catch_all_web_mount_to_end()
app = base.app
