from __future__ import annotations

from pathlib import Path

from mail_agent_core.models import AgentBehaviorSettings, MailCategory, MailHandlingAction


ROOT = Path(__file__).resolve().parents[1]


def test_behavior_defaults_mark_successfully_processed_mail_read():
    behavior = AgentBehaviorSettings()
    assert behavior.mark_processed_read is True
    assert behavior.newsletter_action == MailHandlingAction.NONE
    assert behavior.advertising_action == MailHandlingAction.NONE
    assert MailCategory.ADVERTISING.value == "advertising"


def test_runtime_applies_category_handling_and_retryable_mark_read_postprocess():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    store = (ROOT / "apps/gateway/mail_agent_gateway/mail_store.py").read_text(encoding="utf-8")
    assert 'metadata["deterministic_category_handling"]' in source
    assert "behavior.newsletter_action" in source
    assert "behavior.advertising_action" in source
    assert "async def _reconcile_processed_read" in source
    assert "list_processed_unread" in source
    assert "agent_postprocess_mark_read_failed" in source
    assert "not policy.allowed or policy.requires_approval" in source
    assert "p.status='processed'" in store


def test_prompt_distinguishes_newsletter_and_advertising():
    source = (ROOT / "packages/agent_core/mail_agent_core/agent.py").read_text(encoding="utf-8")
    assert "category `advertising` for direct promotions" in source
    assert "category `newsletter` for recurring editorial" in source


def test_shadow_cycle_stays_remote_side_effect_free():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    shadow = source[source.index("async def _run_shadow_mailbox"):source.index("async def _reconcile_processed_read")]
    assert "execute_direct" not in shadow
