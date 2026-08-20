from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from . import main_v16 as previous
from .calendar_assistant import CalendarAssistant, CalendarAssistantRequest
from .calendar_service import (
    CalendarApprovalStore,
    CalendarFreeBusyRequest,
    CalendarProposalRequest,
    CalendarService,
)
from .schemas import ApprovalDecisionRequest, OAuthStartRequest

APP_VERSION = "0.17.0"
base = previous.base

# 0.17 adds Calendar as a capability on top of the fully verified 0.16.1 runtime. The existing
# policy engine, mail approval queue, action executor, identity and adaptive mail reasoning remain
# authoritative and untouched.
previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION

calendar_store = CalendarApprovalStore(base.settings.data_dir / "calendar.db")
calendar_service = CalendarService(
    store=calendar_store,
    mailbox_lookup=base._mailbox_by_id,
    mailbox_supplier=base._configured_mailboxes,
    vault=base.vault,
    google_client_id=base.settings.google_client_id,
    google_client_secret=base.settings.google_client_secret,
    audit_log=base.audit_log,
)
calendar_assistant = CalendarAssistant(
    calendar_service=calendar_service,
    model_router=previous.model_router,
    providers=base.providers,
    mail_store=base.mail_store,
)


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
        title = "Google-Kalender-Verbindung abgebrochen" if purpose == "calendar" else "Google-Anmeldung abgebrochen"
        return base.HTMLResponse(base._oauth_result_page(False, title, message))
    if not code:
        base.oauth_controller.fail(
            state=state,
            provider="google",
            error="Authorization code is missing",
        )
        title = "Google Kalender konnte nicht verbunden werden" if purpose == "calendar" else "Google-Anmeldung fehlgeschlagen"
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
                    f"{result.get('email_address') or 'Das Google-Konto'} darf jetzt Termine lesen und nach Freigabe verwalten.",
                )
            )
        return base.HTMLResponse(
            base._oauth_result_page(
                True,
                "Gmail ist verbunden",
                f"{result.get('email_address') or 'Das Postfach'} wurde sicher mit MAIL-AGENT verbunden.",
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="OAuth session not found or expired") from exc
    except Exception as exc:
        title = "Google Kalender konnte nicht verbunden werden" if purpose == "calendar" else "Google-Anmeldung fehlgeschlagen"
        return base.HTMLResponse(base._oauth_result_page(False, title, str(exc)), status_code=502)


# Existing callback routes resolve this function from main.py's module globals at request time.
# Replacing only the presentation wrapper keeps one callback URI for Gmail and Calendar upgrades.
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
    return calendar_service.status()


@base.app.get("/v1/calendar/calendars")
async def calendar_list(mailbox_id: str) -> dict[str, Any]:
    try:
        return {"calendars": await calendar_service.calendars(mailbox_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown Google account") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar request failed: {exc}") from exc


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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown Google account") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar request failed: {exc}") from exc
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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown Google account") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar request failed: {exc}") from exc


@base.app.post("/v1/calendar/assist")
async def calendar_assist(body: CalendarAssistantRequest) -> dict[str, Any]:
    try:
        return await calendar_assistant.propose(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Calendar account or source message not found") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Calendar assistant failed: {exc}") from exc


@base.app.post("/v1/calendar/proposals")
async def calendar_propose(body: CalendarProposalRequest) -> dict[str, Any]:
    try:
        return calendar_service.propose(body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown Google account") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Calendar approval not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        status = 502 if message.startswith("Approved calendar action could not be executed:") else 409
        raise HTTPException(status_code=status, detail=message) from exc


@base.app.post("/v1/calendar/approvals/{approval_id}/reject")
async def reject_calendar_action(
    approval_id: str,
    body: ApprovalDecisionRequest,
) -> dict[str, Any]:
    try:
        return calendar_service.reject(approval_id, actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Calendar approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
