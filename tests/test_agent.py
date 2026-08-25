import asyncio
from pathlib import Path

from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_core.signature import assert_mandatory_agent_signature


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self.request: CompletionRequest | None = None

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        self.request = request
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


def test_authenticated_owner_instruction_is_separate_from_untrusted_mail(tmp_path: Path):
    provider = FakeProvider()
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="work")
    asyncio.run(
        MailAgent().analyze(
            profile=AgentProfile(
                owner_id="owner",
                agent_name="Nova",
                usage_type=UsageType.WORK,
                autonomy_mode=AutonomyMode.COPILOT,
            ),
            provider=provider,
            model="fake",
            message=MailMessageContext(
                mailbox_id="mailbox",
                message_id="message",
                sender="sender@example.test",
                subject="Termin",
                body="Untrusted email content",
            ),
            identity=identity,
            sign_payload=manager.sign,
            owner_instruction="Bestätige den Termin freundlich.",
        )
    )

    import json

    payload = json.loads(provider.request.user)
    assert payload["owner_instruction"] == "Bestätige den Termin freundlich."
    assert payload["mail"]["body"] == "Untrusted email content"
    assert "AUTHENTICATED OWNER-DIRECTED MODE" in provider.request.system
