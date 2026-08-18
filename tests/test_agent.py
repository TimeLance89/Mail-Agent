import asyncio
from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.identity import AgentIdentity
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth


class FakeProvider(LLMProvider):
    name = "fake"

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        return '''{
          "action": "send_reply",
          "mailbox_id": "attacker-mailbox",
          "message_id": "attacker-message",
          "recipient": "person@example.com",
          "subject": "Re: Hello",
          "body": "Thanks",
          "confidence": 0.91,
          "reason": "Reply requested"
        }'''


def test_agent_overwrites_model_controlled_scope_and_applies_policy():
    agent = MailAgent()
    profile = AgentProfile(
        owner_id="owner",
        agent_name="Nova",
        usage_type=UsageType.WORK,
        autonomy_mode=AutonomyMode.AUTONOMOUS,
    )
    message = MailMessageContext(
        mailbox_id="trusted-mailbox",
        message_id="trusted-message",
        thread_id="trusted-thread",
        sender="person@example.com",
        recipients=["owner@example.com"],
        subject="Hello",
        body="Please reply",
    )
    identity = AgentIdentity(
        owner_id="owner",
        agent_id="ma_test",
        installation_id="inst_test",
        agent_name="Nova",
        usage_type="work",
        public_key="public",
        fingerprint="f" * 64,
        created_at="2026-01-01T00:00:00+00:00",
    )
    result = asyncio.run(
        agent.analyze(
            profile=profile,
            provider=FakeProvider(),
            model="fake",
            message=message,
            identity=identity,
        )
    )
    assert result.proposal.mailbox_id == "trusted-mailbox"
    assert result.proposal.message_id == "trusted-message"
    assert result.proposal.thread_id == "trusted-thread"
    assert result.policy.allowed
    assert result.policy.requires_approval
    assert result.policy.risk == "high"
    assert "Agent-ID: ma_test" in result.proposal.body
    assert result.proposal.metadata["agent_signature_required"] is True
