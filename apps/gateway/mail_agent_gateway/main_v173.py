from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mail_agent_core.models import AgentBehaviorSettings, AgentExecutionMode, AgentProfile, AutonomyMode

from . import main_v172 as previous
from .calendar_concierge import CalendarConciergeRequest
from .daily_briefing import build_daily_briefing
from .calendar_mail_intent import calendar_mail_suggestions
from .calendar_reliable import ReliableCalendarProposal, ReliableCalendarProposalRequest
from .calendar_service import CalendarAction

APP_VERSION = "0.17.3"
base = previous.base
calendar_service = previous.calendar_service
calendar_store = previous.calendar_store
calendar_concierge = previous.calendar_concierge
owner_profile_store = previous.previous.previous.previous.owner_profile_store

previous.APP_VERSION = APP_VERSION
previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION

_DISALLOWED_AUTO_CATEGORIES = {"advertising", "cold_outreach", "newsletter", "security"}


def _profile_and_behavior() -> tuple[AgentProfile, AgentBehaviorSettings]:
    state = base.state_store.read()
    config = state.get("configuration")
    if not state.get("onboarding_completed") or not isinstance(config, dict):
        raise RuntimeError("Onboarding is not complete")
    profile = AgentProfile.model_validate(config["profile"])
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    return profile, behavior


def _autonomous_live() -> bool:
    try:
        profile, behavior = _profile_and_behavior()
    except Exception:
        return False
    return bool(
        profile.autonomy_mode == AutonomyMode.AUTONOMOUS
        and behavior.enabled
        and behavior.execution_mode == AgentExecutionMode.LIVE
    )


def _safe_autonomous_create(
    proposal: Any,
    *,
    allow_conflict: bool,
) -> bool:
    if not _autonomous_live():
        return False
    if proposal.action != CalendarAction.CREATE or proposal.event is None:
        return False
    if allow_conflict or proposal.send_updates != "none":
        return False
    if proposal.event.attendees:
        return False
    return True


def _autonomy_trace(
    *,
    mailbox_id: str,
    message_id: str | None,
    subject: str,
    detail: str,
    status: str,
    outcome: str,
    approval_id: str | None = None,
    execution_status: str | None = None,
) -> None:
    trace_id = "calauto_" + uuid.uuid4().hex
    base.agent_runtime.activity.record(
        trace_id=trace_id,
        stage="calendar",
        status=status,
        detail=detail,
        mailbox_id=mailbox_id,
        message_id=message_id,
        subject=subject,
        data={
            "trigger": "autonomous_calendar",
            "action": "create",
            "approval_id": approval_id,
            "execution_status": execution_status,
            "side_effects": outcome == "calendar_auto_scheduled",
        },
    )
    base.agent_runtime.activity.finish(trace_id, outcome=outcome, reason=detail)


def _init_autonomy_state() -> None:
    with calendar_store._lock, calendar_store._connect() as conn:  # noqa: SLF001 - same local DB boundary
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_autonomy_mail (
                mailbox_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (mailbox_id, message_id)
            )
            """
        )


def _autonomy_mail_state(mailbox_id: str, message_id: str) -> str | None:
    with calendar_store._lock, calendar_store._connect() as conn:  # noqa: SLF001
        row = conn.execute(
            "SELECT status FROM calendar_autonomy_mail WHERE mailbox_id=? AND message_id=?",
            (mailbox_id, message_id),
        ).fetchone()
    return str(row["status"]) if row else None


def _set_autonomy_mail_state(mailbox_id: str, message_id: str, status: str, detail: str) -> None:
    from .calendar_service import utc_now

    with calendar_store._lock, calendar_store._connect() as conn:  # noqa: SLF001
        conn.execute(
            """
            INSERT INTO calendar_autonomy_mail(mailbox_id, message_id, status, detail, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at
            """,
            (mailbox_id, message_id, status, detail[:1000], utc_now()),
        )


def _approval_for_source(mailbox_id: str, message_id: str) -> dict[str, Any] | None:
    with calendar_store._lock, calendar_store._connect() as conn:  # noqa: SLF001
        rows = conn.execute(
            "SELECT * FROM calendar_approvals WHERE mailbox_id=? ORDER BY created_at DESC LIMIT 500",
            (mailbox_id,),
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["proposal_json"])
        except (TypeError, ValueError):
            continue
        if str(payload.get("source_message_id") or "") == message_id:
            return calendar_store._row(row)  # noqa: SLF001
    return None


_init_autonomy_state()


# In Autonomous mode, a conflict-free CREATE that cannot contact third parties is not a human-
# approval task. It still goes through the proposal store, atomic claim, conflict re-check and
# reliable executor; the only skipped step is the redundant owner click.
if not getattr(calendar_service, "_v173_autonomy_patch", False):
    _original_propose_checked = calendar_service.propose_checked

    async def _propose_checked_v173(
        request: ReliableCalendarProposalRequest,
    ) -> dict[str, Any]:
        result = await _original_propose_checked(request)
        if not _safe_autonomous_create(
            request.proposal,
            allow_conflict=bool(getattr(request, "allow_conflict", False)),
        ):
            return result
        executed = await calendar_service.approve(
            result["approval_id"],
            actor="autonomous-agent",
        )
        executed["autonomous_execution"] = True
        executed["autonomous_reason"] = (
            "Autonomous mode: conflict-free local calendar create without attendees or external updates"
        )
        base.audit_log.append(
            "calendar_action_autonomously_approved",
            actor="autonomous-agent",
            details={
                "approval_id": result["approval_id"],
                "mailbox_id": request.proposal.mailbox_id,
                "calendar_id": request.proposal.calendar_id,
                "source_message_id": request.proposal.source_message_id,
            },
        )
        return executed

    calendar_service.propose_checked = _propose_checked_v173  # type: ignore[method-assign]
    calendar_service._v173_autonomy_patch = True  # type: ignore[attr-defined]


# Make the assistant response match what actually happened. Risky or ambiguous actions still return
# a normal proposal/clarification and therefore keep their human-in-the-loop UI.
if not getattr(calendar_concierge, "_v173_autonomy_response_patch", False):
    _original_assist = calendar_concierge.assist

    async def _assist_v173(request: CalendarConciergeRequest) -> dict[str, Any]:
        result = await _original_assist(request)
        approval = result.get("approval") if isinstance(result, dict) else None
        if not isinstance(approval, dict) or not approval.get("autonomous_execution"):
            return result
        result["kind"] = "executed"
        followup = approval.get("mail_followup") or {}
        pending_reply = isinstance(followup, dict) and isinstance(followup.get("approval"), dict)
        suffix = (
            " Die Bestätigungsantwort ist vorbereitet und wartet nur noch auf die separate Versandfreigabe."
            if pending_reply
            else ""
        )
        result["answer"] = (
            "Autonomous hat den eindeutigen, konfliktfreien Termin selbst in deinen Kalender eingetragen."
            + suffix
        )
        return result

    calendar_concierge.assist = _assist_v173  # type: ignore[method-assign]
    calendar_concierge._v173_autonomy_response_patch = True  # type: ignore[attr-defined]


async def _finish_pending_autonomous_creates(mailbox_id: str) -> int:
    if not _autonomous_live():
        return 0
    completed = 0
    for approval in calendar_store.list("pending", 100):
        if approval.get("mailbox_id") != mailbox_id:
            continue
        try:
            proposal = ReliableCalendarProposal.model_validate(approval["proposal"])
        except Exception:
            continue
        if not _safe_autonomous_create(proposal, allow_conflict=bool(proposal.allow_conflict)):
            continue
        assert proposal.event is not None
        conflicts = await calendar_service.conflicts_for_event(
            proposal.mailbox_id,
            calendar_id=proposal.calendar_id,
            event=proposal.event,
        )
        if conflicts:
            continue
        result = await calendar_service.approve(
            approval["approval_id"],
            actor="autonomous-agent",
        )
        completed += 1
        source_id = str(proposal.source_message_id or "")
        if source_id:
            _set_autonomy_mail_state(
                mailbox_id,
                source_id,
                "completed",
                "Eindeutiger Termin wurde im Autonomous-Modus automatisch eingetragen.",
            )
        _autonomy_trace(
            mailbox_id=mailbox_id,
            message_id=source_id or None,
            subject=str(proposal.event.summary or "Termin"),
            detail="Eindeutigen, konfliktfreien Termin automatisch eingetragen.",
            status="completed",
            outcome="calendar_auto_scheduled",
            approval_id=approval["approval_id"],
            execution_status=result.get("execution_status"),
        )
    return completed


async def _process_autonomous_calendar_mail(mailbox_id: str) -> dict[str, Any]:
    if not _autonomous_live():
        return {"enabled": False, "scheduled": 0, "needs_attention": 0}

    status = calendar_service.status()
    account = next(
        (item for item in status.get("accounts", []) if item.get("mailbox_id") == mailbox_id),
        None,
    )
    if not account or not account.get("connected"):
        return {"enabled": True, "calendar_connected": False, "scheduled": 0, "needs_attention": 0}

    scheduled = await _finish_pending_autonomous_creates(mailbox_id)
    needs_attention = 0
    suggestions = calendar_mail_suggestions(base.mail_store, mailbox_id, limit=80)
    for item in reversed(suggestions):
        message_id = str(item.get("message_id") or "")
        if not message_id or _autonomy_mail_state(mailbox_id, message_id):
            continue
        if _approval_for_source(mailbox_id, message_id) is not None:
            continue
        if (
            item.get("intent") != "schedule_request"
            or not item.get("has_explicit_time")
            or not item.get("has_date_context")
            or not item.get("needs_reply")
        ):
            continue

        message = base.mail_store.get_message(mailbox_id, message_id)
        if message is None:
            continue
        category = str(message.get("agent_category") or "").casefold()
        if category in _DISALLOWED_AUTO_CATEGORIES:
            _set_autonomy_mail_state(
                mailbox_id,
                message_id,
                "needs_attention",
                f"Automatische Terminannahme für Kategorie {category or 'unbekannt'} blockiert.",
            )
            needs_attention += 1
            continue

        try:
            result = await calendar_concierge.assist(
                CalendarConciergeRequest(
                    mailbox_id=mailbox_id,
                    instruction=(
                        "Trage den konkret angefragten Termin aus dieser Mail ein, wenn Datum und Uhrzeit "
                        "eindeutig sind und der Zeitraum frei ist. Bei Konflikt oder Unklarheit nichts ändern."
                    ),
                    calendar_id="primary",
                    duration_minutes=60,
                    source_message_id=message_id,
                    actor="autonomous-agent",
                )
            )
        except Exception as exc:
            detail = f"Autonome Kalenderprüfung fehlgeschlagen: {exc}"
            _set_autonomy_mail_state(mailbox_id, message_id, "needs_attention", detail)
            needs_attention += 1
            _autonomy_trace(
                mailbox_id=mailbox_id,
                message_id=message_id,
                subject=str(message.get("subject") or "Termin"),
                detail=detail,
                status="failed",
                outcome="needs_attention",
            )
            continue

        approval = result.get("approval") if isinstance(result, dict) else None
        if isinstance(approval, dict) and approval.get("autonomous_execution"):
            scheduled += 1
            _set_autonomy_mail_state(
                mailbox_id,
                message_id,
                "completed",
                "Eindeutiger Termin wurde im Autonomous-Modus automatisch eingetragen.",
            )
            try:
                base.mail_store.resolve_attention(
                    mailbox_id,
                    message_id,
                    owner_note="Termin im Autonomous-Modus automatisch eingetragen; ausgehende Bestätigung separat abgesichert.",
                )
            except Exception:
                pass
            _autonomy_trace(
                mailbox_id=mailbox_id,
                message_id=message_id,
                subject=str(message.get("subject") or "Termin"),
                detail="Eindeutigen, konfliktfreien Termin automatisch eingetragen.",
                status="completed",
                outcome="calendar_auto_scheduled",
                approval_id=approval.get("approval_id"),
                execution_status=approval.get("execution_status"),
            )
            continue

        detail = str(result.get("answer") or "Termin braucht eine Entscheidung des Besitzers.")
        _set_autonomy_mail_state(mailbox_id, message_id, "needs_attention", detail)
        needs_attention += 1
        _autonomy_trace(
            mailbox_id=mailbox_id,
            message_id=message_id,
            subject=str(message.get("subject") or "Termin"),
            detail=detail,
            status="completed",
            outcome="needs_attention",
        )

    return {
        "enabled": True,
        "calendar_connected": True,
        "scheduled": scheduled,
        "needs_attention": needs_attention,
    }


# Auto-sync is the natural trigger for Autonomous scheduling. The mail agent first analyzes the new
# messages; only afterwards do we inspect strong scheduling candidates using the now-populated
# needs_reply/category metadata. A calendar failure never breaks mailbox synchronization.
if not getattr(base, "_v173_calendar_sync_patch", False):
    _original_sync_mailbox = base._sync_mailbox

    async def _sync_mailbox_v173(mailbox: dict[str, Any], *, limit: int = 100) -> dict[str, Any]:
        result = await _original_sync_mailbox(mailbox, limit=limit)
        mailbox_id = str(mailbox.get("mailbox_id") or "")
        if mailbox_id and mailbox.get("connector") == "gmail_api":
            try:
                result["calendar_autonomy"] = await _process_autonomous_calendar_mail(mailbox_id)
            except Exception as exc:
                result["calendar_autonomy"] = {"enabled": _autonomous_live(), "error": str(exc)}
                base.audit_log.append(
                    "calendar_autonomy_cycle_failed",
                    details={"mailbox_id": mailbox_id, "error": str(exc)[:2000]},
                )
        return result

    base._sync_mailbox = _sync_mailbox_v173
    base._v173_calendar_sync_patch = True


# Preserve the meaning of direct_write_allowed: the LLM still has no direct Calendar executor. The
# new flag communicates that the deterministic policy layer may auto-approve narrowly safe creates.
if not getattr(calendar_service, "_v173_status_patch", False):
    _original_status = calendar_service.status

    def _status_v173() -> dict[str, Any]:
        result = _original_status()
        result["autonomy_mode"] = (
            _profile_and_behavior()[0].autonomy_mode.value
            if base.state_store.read().get("onboarding_completed")
            else None
        )
        result["autonomous_safe_create_allowed"] = _autonomous_live()
        result["direct_write_allowed"] = False
        return result

    calendar_service.status = _status_v173  # type: ignore[method-assign]
    calendar_service._v173_status_patch = True  # type: ignore[attr-defined]


async def _today_calendar_events(mailbox_id: str | None) -> tuple[list[dict[str, Any]], str | None]:
    status = calendar_service.status()
    accounts = [item for item in status.get("accounts", []) if item.get("connected")]
    if mailbox_id:
        accounts = [item for item in accounts if item.get("mailbox_id") == mailbox_id]
    if not accounts:
        return [], "not_connected"
    selected_mailbox = str(accounts[0].get("mailbox_id") or "")
    try:
        calendars = await calendar_service.calendars(selected_mailbox)
        primary = next((item for item in calendars if item.get("primary")), None)
        if primary is None:
            return [], "primary_calendar_unavailable"
        zone_name = str(primary.get("time_zone") or "UTC")
        try:
            zone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local_now = datetime.now(UTC).astimezone(zone)
        day_end = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        events = await calendar_service.events(
            selected_mailbox,
            calendar_id=str(primary.get("id") or "primary"),
            time_min=local_now.isoformat(),
            time_max=day_end.isoformat(),
            max_results=100,
        )
        return events, None
    except Exception as exc:
        return [], str(exc)[:500]


@base.app.get("/v1/briefing")
async def daily_briefing(mailbox_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Return one deterministic, task-first view of the owner's current work.

    This endpoint only composes existing local agent state plus a read-only Calendar agenda. It does
    not invoke an LLM and cannot execute mail or Calendar mutations.
    """

    base._configuration_or_409()
    if mailbox_id:
        try:
            base._mailbox_by_id(mailbox_id)
        except KeyError as exc:
            raise base.HTTPException(status_code=404, detail="Unknown mailbox") from exc

    pending_approvals = base.mail_store.list_approvals("pending", 100)
    recoverable_approvals = [
        item
        for item in base.mail_store.list_approvals("approved", 100)
        if item.get("execution_status") in {"failed", "uncertain", "ready"}
    ]
    approvals = sorted(
        pending_approvals + recoverable_approvals,
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )
    conversations = base.conversation_store.list_threads(
        mailbox_id=mailbox_id,
        limit=300,
        include_snoozed=False,
    )
    calendar_approvals = [
        item
        for item in calendar_store.list("pending", 100)
        if not mailbox_id or item.get("mailbox_id") == mailbox_id
    ]
    calendar_events, calendar_error = await _today_calendar_events(mailbox_id)
    owner_profile = owner_profile_store.public()
    learning_enabled = bool(owner_profile.get("consent"))
    pending_profile = (
        len(owner_profile.get("preview") or [])
        if owner_profile.get("status") == "preview_ready"
        else 0
    )
    pending_corrections = (
        len(base.agent_runtime.brain.learning_candidates()) if learning_enabled else 0
    )
    return build_daily_briefing(
        attention=base.mail_store.list_attention(mailbox_id, 200),
        approvals=approvals,
        drafts=base.mail_store.list_drafts(mailbox_id, 200),
        conversations=conversations,
        calendar_approvals=calendar_approvals,
        calendar_events=calendar_events,
        calendar_error=calendar_error,
        learning={
            "enabled": learning_enabled,
            "status": str(owner_profile.get("status") or "not_asked"),
            "confirmed_preferences": len(owner_profile.get("active") or []),
            "pending_suggestions": pending_profile + pending_corrections,
            "profile_version": int(owner_profile.get("profile_version") or 0),
        },
        limit=limit,
    )


previous.previous._move_catch_all_web_mount_to_end()
app = base.app
