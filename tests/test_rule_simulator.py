from __future__ import annotations

from mail_agent_core.agent import MailAgent
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentProfile,
    AutonomyMode,
    MailActionType,
    MailCategory,
    MailPriority,
    UsageType,
)
from mail_agent_core.policy import PolicyEngine
from mail_agent_gateway.agent_runtime import AgentRuntime
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore
from mail_agent_gateway.state import JsonStateStore


def make_runtime(tmp_path, *, rules):
    store = MailStore(tmp_path / "mail.db")
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner", agent_name="Nova", usage_type="work")
    state = JsonStateStore(tmp_path / "state.json")
    profile = AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.WORK,
        autonomy_mode=AutonomyMode.COPILOT,
    )
    state.write(
        {
            "onboarding_completed": True,
            "configuration": {
                "profile": profile.model_dump(mode="json"),
                "provider": "fake",
                "model": "fake",
                "behavior": {
                    "execution_mode": "live",
                    "minimum_confidence": 0.72,
                    "auto_create_drafts": True,
                    "rules": rules,
                },
            },
        }
    )
    return AgentRuntime(
        mail_agent=MailAgent(PolicyEngine()),
        identity_manager=identity,
        mail_store=store,
        state_store=state,
        providers={},
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )


def test_rule_simulator_downgrades_send_to_draft_without_side_effects(tmp_path):
    runtime = make_runtime(
        tmp_path,
        rules=[
            {
                "pattern": "@firma.de",
                "mode": "draft_only",
                "priority": "urgent",
                "category": "work",
            }
        ],
    )

    result = runtime.simulate_rule(
        sender="boss@firma.de",
        action=MailActionType.SEND_REPLY,
        confidence=0.94,
        priority=MailPriority.NORMAL,
        category=MailCategory.OTHER,
        needs_reply=True,
    )

    assert result["shadow"] is True
    assert result["side_effects"] == 0
    assert result["matched_rule"]["pattern"] == "@firma.de"
    assert result["rule_mode"] == "draft_only"
    assert result["original_action"] == "send_reply"
    assert result["resulting_action"] == "create_draft"
    assert result["priority"] == "urgent"
    assert result["category"] == "work"
    assert result["planned_artifacts"] == ["draft"]
    assert result["simulated_outcome"] == "would_draft"


def test_rule_simulator_reports_high_impact_approval_without_creating_one(tmp_path):
    runtime = make_runtime(tmp_path, rules=[])

    result = runtime.simulate_rule(
        sender="person@example.test",
        action=MailActionType.DELETE,
        confidence=0.99,
        priority=MailPriority.NORMAL,
        category=MailCategory.OTHER,
        needs_reply=False,
    )

    assert result["policy"]["allowed"] is True
    assert result["policy"]["requires_approval"] is True
    assert result["planned_artifacts"] == ["approval"]
    assert result["simulated_outcome"] == "would_approval"
    assert result["side_effects"] == 0
