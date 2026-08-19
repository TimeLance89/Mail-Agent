from __future__ import annotations

import asyncio
import json

from mail_agent_core.agent import MailAgent
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_gateway.agent_runtime import AgentRuntime
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


class ShadowProvider(LLMProvider):
    name = "fake"

    def __init__(self, action: str = "send_reply"):
        self.action = action
        self.calls = 0

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        self.calls += 1
        body = "Prepared reply" if self.action in {"send_reply", "forward", "create_draft"} else None
        return json.dumps(
            {
                "action": self.action,
                "mailbox_id": "model",
                "message_id": "model",
                "recipient": "attacker@example.test",
                "subject": "Re: Hello",
                "body": body,
                "confidence": 0.95,
                "reason": "A reply is needed",
                "summary": "Test mail",
                "priority": "high",
                "category": "work",
                "needs_reply": True,
            }
        )


class RecordingExecutor:
    def __init__(self):
        self.actions: list[str] = []

    async def execute_direct(self, proposal):
        self.actions.append(proposal.action.value)
        return {"execution_status": "completed", "action": proposal.action.value}


def make_runtime(tmp_path, *, action="send_reply", execution_mode="shadow"):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<m1@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Hello",
                sent_at="2026-08-19T08:00:00+00:00",
                body_text="Please answer this message",
                seen=False,
                remote_id="m1",
            )
        ]
    )
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
                    "enabled": True,
                    "execution_mode": execution_mode,
                    "auto_analyze_new_mail": True,
                    "auto_create_drafts": True,
                    "minimum_confidence": 0.7,
                    "max_messages_per_cycle": 20,
                },
            },
        }
    )
    provider = ShadowProvider(action)
    executor = RecordingExecutor()
    runtime = AgentRuntime(
        mail_agent=MailAgent(PolicyEngine()),
        identity_manager=identity,
        mail_store=store,
        state_store=state,
        providers={"fake": provider},
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        action_executor=executor,
    )
    return runtime, store, state, provider, executor


def test_shadow_cycle_creates_no_drafts_approvals_execution_or_live_processing(tmp_path):
    runtime, store, _state, _provider, executor = make_runtime(tmp_path)

    result = asyncio.run(runtime.run_mailbox("mb", force=True))

    assert result["execution_mode"] == "shadow"
    assert result["side_effects"] == 0
    assert result["drafts"] == 0
    assert result["approvals"] == 0
    assert result["executed"] == 0
    assert result["would_approval"] == 1
    assert executor.actions == []
    assert store.list_drafts("mb") == []
    assert store.list_approvals("pending") == []
    assert store.is_agent_processed("mb", "m1") is False
    assert store.is_shadow_processed("mb", "m1") is True
    stored = store.get_message("mb", "m1")
    assert stored["analyzed_at"] is None
    assert stored["agent_summary"] is None


def test_switching_from_shadow_to_live_does_not_lose_the_mail(tmp_path):
    runtime, store, state, _provider, _executor = make_runtime(tmp_path)
    asyncio.run(runtime.run_mailbox("mb", force=True))

    payload = state.read()
    payload["configuration"]["behavior"]["execution_mode"] = "live"
    state.write(payload)
    live = asyncio.run(runtime.run_mailbox("mb", force=True))

    assert live["execution_mode"] == "live"
    assert live["processed"] == 1
    assert store.is_agent_processed("mb", "m1") is True
    assert len(store.list_approvals("pending")) == 1
    assert len(store.list_drafts("mb")) == 1


def test_historical_replay_does_not_consume_shadow_or_live_queue(tmp_path):
    runtime, store, _state, _provider, executor = make_runtime(tmp_path)

    report = asyncio.run(runtime.shadow_replay("mb", limit=1))

    assert report["side_effects"] == 0
    assert report["analyzed"] == 1
    assert executor.actions == []
    assert store.is_shadow_processed("mb", "m1") is False
    assert store.is_agent_processed("mb", "m1") is False
