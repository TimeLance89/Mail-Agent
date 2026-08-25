from __future__ import annotations

from pathlib import Path

from mail_agent_core.models import AgentBehaviorSettings, AgentProfile, AutonomyMode, UsageType
from mail_agent_gateway.calendar_autonomy_v173 import safe_autonomous_calendar_create
from mail_agent_gateway.calendar_service import CalendarAction, CalendarEventDraft, CalendarProposal


def profile(mode: AutonomyMode) -> AgentProfile:
    return AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.PRIVATE,
        autonomy_mode=mode,
    )


def create_proposal(**updates) -> CalendarProposal:
    payload = {
        "action": CalendarAction.CREATE,
        "mailbox_id": "mb_google",
        "calendar_id": "primary",
        "event": CalendarEventDraft(
            summary="Treffen",
            start="2026-08-22T16:00:00+02:00",
            end="2026-08-22T17:00:00+02:00",
            time_zone="Europe/Berlin",
        ),
        "send_updates": "none",
        "source_message_id": "msg_1",
    }
    payload.update(updates)
    return CalendarProposal.model_validate(payload)


def test_autonomous_safe_local_create_can_skip_redundant_owner_click():
    assert safe_autonomous_calendar_create(
        profile(AutonomyMode.AUTONOMOUS),
        AgentBehaviorSettings(),
        create_proposal(),
        allow_conflict=False,
    ) is True


def test_assistant_and_copilot_keep_calendar_create_human_gated():
    for mode in (AutonomyMode.ASSISTANT, AutonomyMode.COPILOT, AutonomyMode.OBSERVER):
        assert safe_autonomous_calendar_create(
            profile(mode),
            AgentBehaviorSettings(),
            create_proposal(),
            allow_conflict=False,
        ) is False


def test_autonomous_never_skips_approval_for_conflict_invite_update_or_delete():
    autonomous = profile(AutonomyMode.AUTONOMOUS)
    behavior = AgentBehaviorSettings()
    assert safe_autonomous_calendar_create(
        autonomous,
        behavior,
        create_proposal(),
        allow_conflict=True,
    ) is False

    invited = create_proposal(
        event=CalendarEventDraft(
            summary="Treffen",
            start="2026-08-22T16:00:00+02:00",
            end="2026-08-22T17:00:00+02:00",
            attendees=["person@example.com"],
            time_zone="Europe/Berlin",
        ),
        send_updates="all",
    )
    assert safe_autonomous_calendar_create(
        autonomous,
        behavior,
        invited,
        allow_conflict=False,
    ) is False

    update = CalendarProposal(
        action=CalendarAction.UPDATE,
        mailbox_id="mb_google",
        calendar_id="primary",
        event_id="evt_1",
        event=create_proposal().event,
        send_updates="none",
    )
    delete = CalendarProposal(
        action=CalendarAction.DELETE,
        mailbox_id="mb_google",
        calendar_id="primary",
        event_id="evt_1",
        send_updates="none",
    )
    assert safe_autonomous_calendar_create(autonomous, behavior, update, allow_conflict=False) is False
    assert safe_autonomous_calendar_create(autonomous, behavior, delete, allow_conflict=False) is False


def test_shadow_or_paused_agent_never_auto_writes_calendar():
    autonomous = profile(AutonomyMode.AUTONOMOUS)
    paused = AgentBehaviorSettings(enabled=False)
    assert safe_autonomous_calendar_create(autonomous, paused, create_proposal(), allow_conflict=False) is False

    from mail_agent_core.models import AgentExecutionMode

    shadow = AgentBehaviorSettings(execution_mode=AgentExecutionMode.SHADOW)
    assert safe_autonomous_calendar_create(autonomous, shadow, create_proposal(), allow_conflict=False) is False


def test_v173_release_contract_wires_autonomous_sync_and_draft_terminal_filter():
    root = Path(__file__).resolve().parents[1]
    main = (root / "apps/gateway/mail_agent_gateway/main_v173.py").read_text(encoding="utf-8")
    lifecycle = (root / "apps/gateway/mail_agent_gateway/draft_lifecycle_v171.py").read_text(encoding="utf-8")
    launcher = (root / "apps/launcher/mail_agent_launcher_entry.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert "_v173_calendar_sync_patch" in main
    assert "calendar_action_autonomously_approved" in main
    assert "send_updates != \"none\"" in main
    assert "proposal.event.attendees" in main
    assert "CalendarAction.CREATE" in main
    assert "calendar_service.approve" in main
    assert "calendar_concierge.assist" in main
    assert "_TERMINAL_DRAFT_STATUSES = {\"discarded\", \"sent\"}" in lifecycle
    assert "mail_agent_launcher.v190_entry" in launcher
    assert 'version = "0.19.0"' in pyproject
    assert 'mail_agent_launcher.v190_entry:main' in pyproject
