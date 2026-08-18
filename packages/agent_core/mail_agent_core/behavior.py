from __future__ import annotations

from datetime import datetime

from .models import AgentBehaviorSettings


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def behavior_is_active(settings: AgentBehaviorSettings, now: datetime | None = None) -> bool:
    if not settings.enabled:
        return False
    moment = now or datetime.now()
    if moment.weekday() not in settings.active_days:
        return False
    current = moment.hour * 60 + moment.minute
    start = _minutes(settings.active_from)
    end = _minutes(settings.active_until)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def sender_matches(sender: str, candidates: list[str]) -> bool:
    value = sender.strip().lower()
    return any(candidate in value for candidate in candidates)
