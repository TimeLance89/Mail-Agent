from __future__ import annotations

import asyncio
import json

from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_gateway.agent_runtime import AgentRuntime
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


class ActionProvider(LLMProvider):
    name = "fake"

    def __init__(self, action: str):
        self.action = action

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        return json.dumps(
            {
                "action": self.action,
                "mailbox_id": "model",
                "message_id": "model",
                "confidence": 0.95,
                "summary": "test",
                "priority": "normal",
                "category": "other",
                "needs_reply": False,
            }
        )


class RecordingExecutor:
    def __init__(self):
        self.actions = []

    async def execute_direct(self, proposal):
        self.actions.append(proposal.action.value)
        return {"action": proposal.action.value, "connector": "fake"}


def make_runtime(tmp_path, action: str):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<m@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Hello",
                sent_at=None,
                body_text="Body",
                seen=False,
            )
        ]
    )
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner", agent_name="Nova", usage_type="private")
    state = JsonStateStore(tmp_path / "state.json")
    profile = AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.PRIVATE,
        autonomy_mode=AutonomyMode.AUTONOMOUS,
    )
    state.write(
        {
            "onboarding_completed": True,
            "configuration": {
                "profile": profile.model_dump(mode="json"),
                "provider": "fake",
                "model": "fake",
                "behavior": {"minimum_confidence": 0.7},
            },
        }
    )
    executor = RecordingExecutor()
    runtime = AgentRuntime(
        mail_agent=MailAgent(PolicyEngine()),
        identity_manager=identity,
        mail_store=store,
        state_store=state,
        providers={"fake": ActionProvider(action)},
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        action_executor=executor,
    )
    return runtime, store, executor


def message():
    return MailMessageContext(
        mailbox_id="mb",
        message_id="1",
        thread_id="thread",
        sender="person@example.test",
        recipients=["owner@example.test"],
        subject="Hello",
        body="Body",
    )


def test_mark_read_executes_directly_when_policy_requires_no_approval(tmp_path):
    runtime, _store, executor = make_runtime(tmp_path, "mark_read")
    result = asyncio.run(runtime.analyze_message(message()))
    assert result["approval"] is None
    assert result["execution"]["action"] == "mark_read"
    assert executor.actions == ["mark_read"]


def test_delete_never_reaches_direct_executor_and_enters_approval_queue(tmp_path):
    runtime, store, executor = make_runtime(tmp_path, "delete")
    result = asyncio.run(runtime.analyze_message(message()))
    assert result["execution"] is None
    assert result["approval"] is not None
    assert result["approval"]["action"] == "delete"
    assert executor.actions == []
    assert len(store.list_approvals("pending")) == 1
