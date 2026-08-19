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


class CapturingProvider(LLMProvider):
    name = "fake"

    def __init__(self, action: str = "classify"):
        self.action = action
        self.requests: list[CompletionRequest] = []

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        self.requests.append(request)
        body = "I can help" if self.action in {"send_reply", "forward", "create_draft"} else None
        return json.dumps(
            {
                "action": self.action,
                "mailbox_id": "model-controlled",
                "message_id": "model-controlled",
                "recipient": "attacker@example.test",
                "subject": "Re: Current",
                "body": body,
                "confidence": 0.94,
                "reason": "test",
                "summary": "A concise current-mail summary",
                "priority": "high",
                "category": "work",
                "needs_reply": True,
            }
        )


def make_runtime(tmp_path, provider: CapturingProvider, *, rules=None):
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
                    "enabled": True,
                    "auto_analyze_new_mail": True,
                    "auto_create_drafts": True,
                    "minimum_confidence": 0.7,
                    "thread_context_messages": 8,
                    "rules": rules or [],
                },
            },
        }
    )
    runtime = AgentRuntime(
        mail_agent=MailAgent(PolicyEngine()),
        identity_manager=identity,
        mail_store=store,
        state_store=state,
        providers={"fake": provider},
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    return runtime, store


def seed_thread(store: MailStore):
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb",
                uid=1,
                internet_message_id="<old@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Old",
                sent_at="2026-08-18T10:00:00+00:00",
                body_text="Earlier context",
                seen=True,
                remote_id="old",
            ),
            StoredMessage(
                mailbox_id="mb",
                uid=2,
                internet_message_id="<current@example.test>",
                thread_key="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Current",
                sent_at="2026-08-18T11:00:00+00:00",
                body_text="Current message",
                seen=False,
                remote_id="current",
            ),
        ]
    )


def test_runtime_supplies_thread_context_and_persists_intelligence(tmp_path):
    provider = CapturingProvider("classify")
    runtime, store = make_runtime(tmp_path, provider)
    seed_thread(store)

    result = asyncio.run(
        runtime.analyze_message(
            MailMessageContext(
                mailbox_id="mb",
                message_id="current",
                thread_id="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Current",
                body="Current message",
            )
        )
    )

    request_payload = json.loads(provider.requests[-1].user)
    assert request_payload["mail"]["thread_context"][0]["body"] == "Earlier context"
    stored = store.get_message("mb", "current")
    assert stored["agent_priority"] == "high"
    assert stored["agent_category"] == "work"
    assert stored["agent_summary"] == "A concise current-mail summary"
    assert stored["needs_reply"] is True
    assert result["proposal"]["message_id"] == "current"


def test_draft_only_rule_downgrades_send_reply_and_keeps_authoritative_recipient(tmp_path):
    provider = CapturingProvider("send_reply")
    runtime, store = make_runtime(
        tmp_path,
        provider,
        rules=[{"pattern": "@example.test", "mode": "draft_only", "priority": "urgent"}],
    )
    seed_thread(store)

    result = asyncio.run(
        runtime.analyze_message(
            MailMessageContext(
                mailbox_id="mb",
                message_id="current",
                thread_id="thread",
                sender="person@example.test",
                recipients=["owner@example.test"],
                subject="Current",
                body="Current message",
            )
        )
    )

    assert result["rule_mode"] == "draft_only"
    assert result["proposal"]["action"] == "create_draft"
    assert result["proposal"]["recipient"] == "person@example.test"
    assert result["proposal"]["priority"] == "urgent"
    assert result["approval"] is None
    assert result["draft"] is not None