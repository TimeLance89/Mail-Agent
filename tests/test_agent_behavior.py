from datetime import datetime

from mail_agent_core.behavior import behavior_is_active, sender_matches
from mail_agent_core.models import AgentBehaviorSettings, AgentExecutionMode


def test_behavior_schedule_supports_normal_and_overnight_windows():
    workday = AgentBehaviorSettings(active_days=[0], active_from="08:00", active_until="17:00")
    assert behavior_is_active(workday, datetime(2026, 8, 17, 10, 0))
    assert not behavior_is_active(workday, datetime(2026, 8, 17, 20, 0))

    overnight = AgentBehaviorSettings(active_days=[0], active_from="22:00", active_until="06:00")
    assert behavior_is_active(overnight, datetime(2026, 8, 17, 23, 30))
    assert behavior_is_active(overnight, datetime(2026, 8, 17, 2, 0))


def test_sender_rules_are_case_insensitive():
    assert sender_matches("Boss <boss@Example.com>", ["boss@example.com"])


def test_existing_behavior_without_execution_mode_defaults_to_live():
    behavior = AgentBehaviorSettings.model_validate({"minimum_confidence": 0.72})
    assert behavior.execution_mode == AgentExecutionMode.LIVE
