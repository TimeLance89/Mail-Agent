from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from . import main_v17 as previous
from .calendar_concierge_v171 import TargetedCalendarConcierge
from .mail_store import utc_now
from .schemas import DraftSubmitRequest

APP_VERSION = "0.17.1"
base = previous.base
_original_calendar_http_error = previous._calendar_http_error

previous.APP_VERSION = APP_VERSION
previous.previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION


# Replace only the Calendar concierge. Mail policy, mail executor, identity and both approval
# boundaries remain unchanged.
calendar_concierge = TargetedCalendarConcierge(
    calendar_service=previous.calendar_service,
    model_router=previous.previous.model_router,
    providers=base.providers,
    mail_store=base.mail_store,
    state_store=base.state_store,
    identity_manager=base.identity_manager,
    policy_engine=base.policy_engine,
    audit_log=base.audit_log,
)
previous.calendar_concierge = calendar_concierge


def _google_error_detail(exc: httpx.HTTPStatusError) -> tuple[int, str]:
    response = exc.response
    status = int(response.status_code)
    message = ""
    reason = ""
    try:
        payload = response.json()
        error = payload.get("error") or {}
        message = str(error.get("message") or "").strip()
        errors = error.get("errors") or []
        if errors and isinstance(errors[0], dict):
            reason = str(errors[0].get("reason") or "").strip()
    except Exception:
        message = response.text[:1000].strip()

    normalized = f"{reason} {message}".casefold()
    if status == 401:
        return 401, "Google-Kalender-Anmeldung ist abgelaufen oder ungültig. Bitte Kalender neu verbinden."
    if status == 403:
        if any(
            token in normalized
            for token in (
                "accessnotconfigured",
                "access_not_configured",
                "api has not been used",
                "it is disabled",
                "calendar api has not been used",
            )
        ):
            return 409, (
                "Die Google Calendar API ist für den verwendeten OAuth-Client nicht aktiviert. "
                "Aktiviere die Google Calendar API im Google-Cloud-Projekt und verbinde den Kalender danach erneut."
            )
        if any(
            token in normalized
            for token in (
                "insufficientpermissions",
                "insufficient permission",
                "insufficient authentication scopes",
            )
        ):
            return 409, (
                "Dem Google-Token fehlen Kalender-Berechtigungen. Bitte in MAIL-AGENT "
                "„Berechtigungen erneuern“ verwenden und die Calendar-Rechte bestätigen."
            )
        return 403, f"Google Kalender hat den Zugriff verweigert: {message or reason or 'keine weiteren Details'}"
    if status == 404:
        return 404, "Der angeforderte Google-Kalender oder Termin wurde nicht gefunden."
    if status == 429:
        return 429, "Google Calendar begrenzt die Anfragen gerade. Bitte kurz später erneut versuchen."
    if status >= 500:
        return 502, "Google Calendar ist momentan nicht erreichbar. Bitte später erneut versuchen."
    return status, f"Google Calendar Fehler: {message or reason or f'HTTP {status}'}"


def _calendar_http_error_v171(exc: Exception, *, operation: str) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        status, detail = _google_error_detail(exc)
        return HTTPException(status_code=status, detail=detail)
    if isinstance(exc, httpx.RequestError):
        return HTTPException(
            status_code=503,
            detail="Google Calendar konnte nicht erreicht werden. Prüfe die Internetverbindung und versuche es erneut.",
        )
    return _original_calendar_http_error(exc, operation=operation)


previous._calendar_http_error = _calendar_http_error_v171


# 0.17.1 adds a soft-discard state. Keep discarded drafts for local audit/history while hiding them
# from the ordinary work queue. Pull a wider window first so discarded recent rows do not starve
# older active drafts from the requested limit.
if not getattr(base.mail_store, "_v171_active_draft_filter", False):
    _list_drafts_original = base.mail_store.list_drafts

    def _list_active_drafts(mailbox_id: str | None = None, limit: int = 100):
        requested = max(1, min(int(limit), 500))
        items = _list_drafts_original(mailbox_id, 500)
        return [item for item in items if item.get("status") != "discarded"][:requested]

    base.mail_store.list_drafts = _list_active_drafts  # type: ignore[method-assign]
    base.mail_store._v171_active_draft_filter = True  # type: ignore[attr-defined]


def _discard_draft(draft_id: str, *, actor: str) -> dict[str, Any]:
    store = base.mail_store
    now = utc_now()
    rejected_pending = False
    approval_id: str | None = None
    with store._lock, store._connect() as conn:  # noqa: SLF001 - same local persistence boundary
        row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        if row["status"] == "sent":
            raise RuntimeError("Ein bereits gesendeter Entwurf kann nicht verworfen werden")
        if row["status"] == "discarded":
            return store._draft_row(row)  # noqa: SLF001

        approval_id = row["approval_id"]
        if approval_id:
            approval = conn.execute(
                "SELECT status, execution_status FROM approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
            if approval is None:
                raise RuntimeError("Die verknüpfte Freigabe des Entwurfs fehlt")
            if approval["status"] == "pending":
                conn.execute(
                    """
                    UPDATE approvals
                       SET status='rejected', decided_at=?, decided_by=?, execution_status='not_applicable'
                     WHERE approval_id=? AND status='pending'
                    """,
                    (now, actor, approval_id),
                )
                rejected_pending = True
            elif approval["status"] != "rejected":
                raise RuntimeError(
                    "Die Freigabe wurde bereits erteilt. Prüfe zuerst den Ausführungsstatus, bevor der Entwurf verworfen wird."
                )

        conn.execute(
            """
            UPDATE drafts
               SET status='discarded', updated_at=?, edited_by=?
             WHERE draft_id=?
            """,
            (now, actor, draft_id),
        )
        updated = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()

    base.audit_log.append(
        "draft_discarded",
        actor=actor,
        details={
            "draft_id": draft_id,
            "approval_id": approval_id,
            "pending_approval_rejected": rejected_pending,
        },
    )
    return store._draft_row(updated)  # noqa: SLF001


@base.app.post("/v1/drafts/{draft_id}/discard")
async def discard_draft(draft_id: str, body: DraftSubmitRequest) -> dict[str, Any]:
    try:
        draft = _discard_draft(draft_id, actor=body.actor)
        return {"draft": base.draft_service.public_draft(draft), "discarded": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
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
