import asyncio
from pathlib import Path

from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_core.signature import assert_mandatory_agent_signature


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


def test_agent_overwrites_model_scope_and_cryptographically_signs_reply(tmp_path: Path):
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
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="work")
    result = asyncio.run(
        agent.analyze(
            profile=profile,
            provider=FakeProvider(),
            model="fake",
            message=message,
            identity=identity,
            sign_payload=manager.sign,
        )
    )
    assert result.proposal.mailbox_id == "trusted-mailbox"
    assert result.proposal.message_id == "trusted-message"
    assert result.proposal.thread_id == "trusted-thread"
    assert result.policy.allowed
    assert result.policy.requires_approval
    assert result.policy.risk == "high"
    assert f"Agent-ID: {identity.agent_id}" in result.proposal.body
    assert result.proposal.metadata["agent_signature_required"] is True
    assert result.proposal.metadata["agent_signature_algorithm"] == "ed25519"
    assert_mandatory_agent_signature(result.proposal.body, identity)
