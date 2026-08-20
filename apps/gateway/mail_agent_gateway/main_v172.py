from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import main_v171 as previous
from .calendar_followup_v172 import prepare_calendar_confirmation_followup

APP_VERSION = "0.17.2"
base = previous.base
calendar_service = previous.previous.calendar_service
calendar_store = previous.previous.calendar_store
calendar_concierge = previous.calendar_concierge

previous.APP_VERSION = APP_VERSION
previous.previous.APP_VERSION = APP_VERSION
previous.previous.previous.APP_VERSION = APP_VERSION
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION


async def _prepare_mail_followup(
    approval: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any] | None:
    return await prepare_calendar_confirmation_followup(
        approval,
        mail_store=base.mail_store,
        draft_service=base.draft_service,
        calendar_concierge=calendar_concierge,
        identity_manager=base.identity_manager,
        policy_engine=base.policy_engine,
        audit_log=base.audit_log,
        actor=actor,
    )


# Google can expose a shared calendar as writerWithoutPrivateAccess. It is writable even though
# private event details stay hidden. Normalize the role at the authoritative service boundary so
# UI labels and actual mutation checks cannot disagree.
if not getattr(calendar_service, "_v172_shared_writer_patch", False):
    async def _ensure_writable_calendar_v172(mailbox_id: str, calendar_id: str) -> dict[str, Any]:
        meta = await calendar_service._calendar_meta(mailbox_id, calendar_id)  # noqa: SLF001
        role = str(meta.get("access_role") or "").casefold()
        if role not in {"owner", "writer", "writerwithoutprivateaccess"}:
            raise PermissionError("The selected Google calendar is read-only")
        return meta

    calendar_service._ensure_writable_calendar = _ensure_writable_calendar_v172  # type: ignore[method-assign]  # noqa: SLF001
    calendar_service._v172_shared_writer_patch = True  # type: ignore[attr-defined]


if not getattr(calendar_service, "_v172_mail_followup_patch", False):
    _original_calendar_approve = calendar_service.approve

    async def _approve_with_confirmation_reply(
        approval_id: str,
        *,
        actor: str,
    ) -> dict[str, Any]:
        result = await _original_calendar_approve(approval_id, actor=actor)
        proposal = dict(result.get("proposal") or {})
        source_message_id = str(proposal.get("source_message_id") or "").strip()
        result["mail_followup_required"] = bool(
            source_message_id
            and str(proposal.get("action") or "") in {"create", "update"}
            and result.get("execution_status") == "completed"
        )
        if not result["mail_followup_required"]:
            return result
        try:
            followup = await _prepare_mail_followup(result, actor=actor)
            if followup is not None:
                result["mail_followup"] = followup
        except Exception as exc:
            # The calendar write has already succeeded. Never misreport that as failed merely because
            # preparing the separate, approval-gated outbound reply encountered a problem.
            message = str(exc)[:2000]
            result["mail_followup_error"] = message
            base.audit_log.append(
                "calendar_confirmation_reply_failed",
                actor=actor,
                details={
                    "calendar_approval_id": approval_id,
                    "mailbox_id": result.get("mailbox_id"),
                    "source_message_id": source_message_id,
                    "error": message,
                },
            )
        return result

    calendar_service.approve = _approve_with_confirmation_reply  # type: ignore[method-assign]
    calendar_service._v172_mail_followup_patch = True  # type: ignore[attr-defined]


@base.app.post("/v1/calendar/approvals/{approval_id}/prepare-mail-reply")
async def prepare_calendar_mail_reply(
    approval_id: str,
    actor: str = "local-user",
) -> dict[str, Any]:
    """Retry or explicitly prepare the confirmation reply after calendar execution.

    This endpoint never sends mail. It only creates/reuses a signed draft and puts SEND_REPLY into
    the normal mail approval queue.
    """

    try:
        approval = calendar_store.get(approval_id)
        if approval.get("status") != "approved" or approval.get("execution_status") != "completed":
            raise RuntimeError("Calendar action must be approved and completed first")
        result = await _prepare_mail_followup(approval, actor=actor)
        if result is None:
            raise RuntimeError("This calendar action is not linked to a mail that needs confirmation")
        return {"calendar_approval_id": approval_id, "mail_followup": result}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Calendar approval or source mail not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise previous._calendar_http_error_v171(exc, operation="Calendar confirmation reply") from exc


# The static web mount is a catch-all route. New API routes introduced by this release must remain
# before it so they cannot be swallowed by the frontend.
previous._move_catch_all_web_mount_to_end()
app = base.app
