from __future__ import annotations

from datetime import datetime

from .models import AgentBehaviorSettings, AgentRule, MailCategory, MailPriority, RuleMode


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


def matching_rule(sender: str, settings: AgentBehaviorSettings) -> AgentRule | None:
    value = sender.strip().lower()
    for rule in settings.rules:
        if rule.pattern in value:
            return rule
    return None


def apply_rule_overrides(
    *,
    sender: str,
    settings: AgentBehaviorSettings,
    priority: MailPriority,
    category: MailCategory,
) -> tuple[RuleMode, MailPriority, MailCategory]:
    rule = matching_rule(sender, settings)
    if rule is None:
        if sender_matches(sender, settings.never_auto_act_senders):
            return RuleMode.ANALYZE_ONLY, priority, category
        if sender_matches(sender, settings.vip_senders) and priority in {MailPriority.NORMAL, MailPriority.LOW}:
            priority = MailPriority.HIGH
        return RuleMode.NORMAL, priority, category
    return rule.mode, rule.priority or priority, rule.category or category