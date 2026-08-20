from __future__ import annotations

import re
from typing import Any

_STRONG = [
    ("reschedule", re.compile(r"\b(verschieb(?:en|ung)|verlegen|reschedul(?:e|ing)|move\s+(?:the\s+)?meeting)\b", re.I)),
    ("cancellation", re.compile(r"\b(absagen|stornieren|cancel(?:lation|led|ing)?|termin\s+entf[aä]llt)\b", re.I)),
    ("availability", re.compile(r"\b(wann\s+passt|hast\s+du\s+zeit|zeit\s+hast|bist\s+du\s+frei|are\s+you\s+available|when\s+(?:are\s+you|can\s+you)|free\s+slot)\b", re.I)),
    ("schedule_request", re.compile(r"\b(termin|meeting|besprechung|kalender|calendar\s+invite|appointment|schedule|einladung)\b", re.I)),
]
_WEEKDAY = re.compile(
    r"\b(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mo\.?|di\.?|mi\.?|do\.?|fr\.?|sa\.?|so\.?)\b",
    re.I,
)
_TIME = re.compile(r"\b(?:[01]?\d|2[0-3])[:.]\d{2}\s*(?:uhr|h)?\b", re.I)
_DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b")
_RELATIVE = re.compile(r"\b(heute|morgen|übermorgen|nächste\w*\s+woche|today|tomorrow|next\s+week)\b", re.I)


def detect_calendar_intent(message: dict[str, Any]) -> dict[str, Any] | None:
    subject = str(message.get("subject") or "")
    body = str(message.get("body_text") or "")
    text = f"{subject}\n{body[:8000]}"
    score = 0
    reasons: list[str] = []
    intent = "schedule_request"

    for kind, pattern in _STRONG:
        if pattern.search(text):
            score += 3 if kind in {"reschedule", "cancellation", "availability"} else 2
            reasons.append(kind)
            if kind != "schedule_request" or intent == "schedule_request":
                intent = kind
    has_time = bool(_TIME.search(text))
    has_date = bool(_DATE.search(text) or _WEEKDAY.search(text) or _RELATIVE.search(text))
    if has_time:
        score += 1
        reasons.append("explicit_time")
    if has_date:
        score += 1
        reasons.append("date_or_weekday")
    if message.get("needs_reply") is True:
        score += 1
        reasons.append("reply_expected")

    if score < 3:
        return None
    message_id = str(
        message.get("remote_id")
        or message.get("internet_message_id")
        or message.get("uid")
        or ""
    )
    if not message_id:
        return None
    return {
        "mailbox_id": message.get("mailbox_id"),
        "message_id": message_id,
        "thread_id": message.get("thread_key"),
        "sender": message.get("sender"),
        "subject": subject or "(ohne Betreff)",
        "sent_at": message.get("sent_at"),
        "intent": intent,
        "score": score,
        "reasons": reasons,
        "has_explicit_time": has_time,
        "has_date_context": has_date,
        "needs_reply": bool(message.get("needs_reply")),
        "agent_summary": message.get("agent_summary"),
    }


def calendar_mail_suggestions(mail_store: Any, mailbox_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    messages = mail_store.list_messages(mailbox_id, limit=max(1, min(int(limit), 300)))
    suggestions = [item for message in messages if (item := detect_calendar_intent(message))]
    suggestions.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            str(item.get("sent_at") or ""),
        ),
        reverse=True,
    )
    return suggestions[:50]
