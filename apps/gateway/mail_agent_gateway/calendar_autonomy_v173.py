from __future__ import annotations

from mail_agent_core.models import AgentBehaviorSettings, AgentExecutionMode, AgentProfile, AutonomyMode

from .calendar_service import CalendarAction, CalendarProposal


def autonomous_mode_active(profile: AgentProfile, behavior: AgentBehaviorSettings) -> bool:
    return bool(
        profile.autonomy_mode == AutonomyMode.AUTONOMOUS
        and behavior.enabled
        and behavior.execution_mode == AgentExecutionMode.LIVE
    )


def safe_autonomous_calendar_create(
    profile: AgentProfile,
    behavior: AgentBehaviorSettings,
    proposal: CalendarProposal,
    *,
    allow_conflict: bool,
) -> bool:
    """Return whether a Calendar proposal may skip the redundant owner click.

    This is deliberately narrow: Autonomous may create a local calendar entry only when the reliable
    Calendar layer already validated the time, no conflict override is requested, and Google will not
    contact third parties. Update/delete/cancel/invite paths stay human approval-gated.
    """

    if not autonomous_mode_active(profile, behavior):
        return False
    if proposal.action != CalendarAction.CREATE or proposal.event is None:
        return False
    if allow_conflict or proposal.send_updates != "none":
        return False
    if proposal.event.attendees:
        return False
    return True
