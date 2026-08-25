from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_PRIORITY_SCORE = {"urgent": 100, "high": 90, "normal": 70, "low": 50}
_ACTIVE_DRAFT_STATES = {"draft", "approval_pending", "pending"}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _message_id(item: dict[str, Any]) -> str:
    return str(
        item.get("remote_id")
        or item.get("internet_message_id")
        or item.get("uid")
        or ""
    )


def _is_overdue(value: Any, now: datetime) -> bool:
    parsed = _parse_datetime(value)
    return bool(parsed and parsed <= now)


def _focus_item(
    *,
    item_id: str,
    kind: str,
    score: int,
    title: str,
    summary: str,
    view: str,
    action_label: str,
    mailbox_id: str | None = None,
    message_id: str | None = None,
    thread_id: str | None = None,
    due_at: str | None = None,
    created_at: str | None = None,
    source: str = "mail",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "kind": kind,
        "score": max(0, min(int(score), 100)),
        "title": title or "Ohne Betreff",
        "summary": summary,
        "source": source,
        "mailbox_id": mailbox_id,
        "message_id": message_id,
        "thread_id": thread_id,
        "due_at": due_at,
        "created_at": created_at,
        "action": {"view": view, "label": action_label},
        "metadata": metadata or {},
    }


def build_daily_briefing(
    *,
    attention: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    conversations: list[dict[str, Any]],
    calendar_approvals: list[dict[str, Any]] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    calendar_error: str | None = None,
    learning: dict[str, Any] | None = None,
    now: datetime | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Build one task-first briefing from existing local agent state.

    The briefing is deliberately deterministic. It does not ask a model to re-rank private mail and
    it never creates side effects. Existing policy, approval and Calendar executors remain the only
    mutation boundaries.
    """

    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    limit = max(1, min(int(limit), 100))
    focus: list[dict[str, Any]] = []
    seen_messages: set[tuple[str, str]] = set()
    seen_threads: set[tuple[str, str]] = set()

    for item in attention:
        mailbox_id = str(item.get("mailbox_id") or "")
        message_id = _message_id(item)
        priority = str(item.get("agent_priority") or "normal").casefold()
        category = str(item.get("agent_category") or "other").casefold()
        score = _PRIORITY_SCORE.get(priority, 70)
        if category == "security":
            score = max(score, 96)
        if item.get("needs_reply") is True:
            score = max(score, 82)
        focus.append(
            _focus_item(
                item_id=f"attention:{mailbox_id}:{message_id}",
                kind="security" if category == "security" else "decision",
                score=score,
                title=str(item.get("subject") or "Ohne Betreff"),
                summary=str(
                    item.get("agent_summary")
                    or ("Eine Antwort oder Entscheidung ist erforderlich." if item.get("needs_reply") else "Wichtige Nachricht prüfen.")
                ),
                view="attention",
                action_label="Entscheiden",
                mailbox_id=mailbox_id or None,
                message_id=message_id or None,
                created_at=item.get("analyzed_at") or item.get("sent_at"),
                metadata={"priority": priority, "category": category},
            )
        )
        if mailbox_id and message_id:
            seen_messages.add((mailbox_id, message_id))
        thread_id = str(item.get("remote_thread_id") or item.get("thread_key") or "")
        if mailbox_id and thread_id:
            seen_threads.add((mailbox_id, thread_id))

    for item in approvals:
        proposal = dict(item.get("proposal") or {})
        execution = str(item.get("execution_status") or "")
        recovery = execution in {"failed", "uncertain", "ready"}
        action = str(item.get("action") or proposal.get("action") or "")
        outbound = action in {"send_reply", "forward"}
        score = 99 if execution == "uncertain" else 96 if execution == "failed" else 88 if outbound else 84
        focus.append(
            _focus_item(
                item_id=f"approval:{item.get('approval_id')}",
                kind="recovery" if recovery else "approval",
                score=score,
                title=str(proposal.get("subject") or proposal.get("recipient") or "Mail-Aktion freigeben"),
                summary=str(
                    item.get("execution_error")
                    or proposal.get("summary")
                    or proposal.get("reason")
                    or ("Versand prüfen und freigeben." if outbound else "Aktion prüfen und freigeben.")
                ),
                view="approvals",
                action_label="Versand prüfen" if outbound else "Freigabe prüfen",
                mailbox_id=str(proposal.get("mailbox_id") or "") or None,
                message_id=str(proposal.get("message_id") or "") or None,
                thread_id=str(proposal.get("thread_id") or "") or None,
                created_at=item.get("created_at"),
                metadata={"approval_id": item.get("approval_id"), "action": action, "execution_status": execution},
            )
        )

    for item in calendar_approvals or []:
        proposal = dict(item.get("proposal") or {})
        event = dict(proposal.get("event") or {})
        action = str(proposal.get("action") or "create")
        focus.append(
            _focus_item(
                item_id=f"calendar-approval:{item.get('approval_id')}",
                kind="calendar_approval",
                score=86,
                title=str(event.get("summary") or "Kalenderaktion prüfen"),
                summary="Terminänderung benötigt deine Freigabe.",
                view="calendar",
                action_label="Termin prüfen",
                mailbox_id=str(proposal.get("mailbox_id") or "") or None,
                message_id=str(proposal.get("source_message_id") or "") or None,
                due_at=event.get("start"),
                created_at=item.get("created_at"),
                source="calendar",
                metadata={"approval_id": item.get("approval_id"), "action": action},
            )
        )

    waiting: list[dict[str, Any]] = []
    for item in conversations:
        mailbox_id = str(item.get("mailbox_id") or "")
        thread_id = str(item.get("thread_id") or "")
        status = str(item.get("status") or "")
        overdue = _is_overdue(item.get("due_at"), moment)
        compact = {
            "mailbox_id": mailbox_id,
            "thread_id": thread_id,
            "title": str(item.get("subject") or "Ohne Betreff"),
            "summary": str(item.get("rationale") or "Gespräch weiterverfolgen."),
            "due_at": item.get("due_at"),
            "overdue": overdue,
            "followup_draft_id": item.get("followup_draft_id"),
        }
        if status == "awaiting_reply":
            waiting.append(compact)
            continue
        if status != "to_reply" or (mailbox_id, thread_id) in seen_threads:
            continue
        last_message_id = str(item.get("last_message_id") or "")
        if (mailbox_id, last_message_id) in seen_messages:
            continue
        focus.append(
            _focus_item(
                item_id=f"follow-up:{mailbox_id}:{thread_id}",
                kind="follow_up",
                score=94 if overdue else 76,
                title=compact["title"],
                summary=compact["summary"],
                view="inbox",
                action_label="Antwort vorbereiten",
                mailbox_id=mailbox_id or None,
                message_id=last_message_id or None,
                thread_id=thread_id or None,
                due_at=item.get("due_at"),
                created_at=item.get("updated_at"),
                metadata={"overdue": overdue},
            )
        )

    ready_drafts: list[dict[str, Any]] = []
    for item in drafts:
        status = str(item.get("status") or "draft")
        if status not in _ACTIVE_DRAFT_STATES or item.get("approval_id"):
            continue
        ready_drafts.append(
            {
                "draft_id": item.get("draft_id"),
                "mailbox_id": item.get("mailbox_id"),
                "title": str(item.get("subject") or "Antwortentwurf"),
                "recipient": item.get("recipient"),
                "created_at": item.get("updated_at") or item.get("created_at"),
                "action": {"view": "drafts", "label": "Entwurf prüfen"},
            }
        )

    focus.sort(
        key=lambda item: (
            -int(item["score"]),
            _parse_datetime(item.get("due_at") or item.get("created_at")) or datetime.max.replace(tzinfo=UTC),
            item["id"],
        )
    )
    waiting.sort(
        key=lambda item: _parse_datetime(item.get("due_at")) or datetime.max.replace(tzinfo=UTC)
    )
    ready_drafts.sort(
        key=lambda item: _parse_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    schedule = sorted(
        calendar_events or [],
        key=lambda item: str((item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date") or ""),
    )
    total_decisions = len(focus)
    overdue_count = sum(1 for item in focus if item["metadata"].get("overdue")) + sum(
        1 for item in waiting if item["overdue"]
    )
    focus = focus[:limit]
    if total_decisions:
        headline = f"{total_decisions} {'Punkt braucht' if total_decisions == 1 else 'Punkte brauchen'} deine Entscheidung."
        subheadline = "Der Agent hat vorgearbeitet und zeigt dir nur noch die nächsten sinnvollen Schritte."
    elif ready_drafts:
        headline = f"{len(ready_drafts)} {'Antwort ist' if len(ready_drafts) == 1 else 'Antworten sind'} vorbereitet."
        subheadline = "Du kannst die Entwürfe prüfen; Routinearbeit läuft weiter im Hintergrund."
    else:
        headline = "Du musst gerade nichts entscheiden."
        subheadline = "Der Agent hält Postfach, Zusagen und Wiedervorlagen im Blick."

    return {
        "generated_at": moment.isoformat(),
        "headline": headline,
        "subheadline": subheadline,
        "counts": {
            "decisions": total_decisions,
            "ready_drafts": len(ready_drafts),
            "overdue": overdue_count,
            "waiting_on_others": len(waiting),
            "today_events": len(schedule),
        },
        "focus": focus,
        "ready_drafts": ready_drafts[:10],
        "waiting_on_others": waiting[:10],
        "schedule": schedule[:20],
        "calendar": {"available": calendar_error is None, "error": calendar_error},
        "learning": learning
        or {
            "enabled": False,
            "status": "off",
            "confirmed_preferences": 0,
            "pending_suggestions": 0,
            "profile_version": 0,
        },
        "side_effects": False,
    }
