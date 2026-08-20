from __future__ import annotations

import asyncio
from pathlib import Path

from mail_agent_core.agent import MailAgent, MailMessageContext
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, MailActionType, UsageType
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_core.signature import assert_mandatory_agent_signature
from mail_agent_gateway.conversation_store import ConversationStore
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.undo_service import UndoService


class FollowUpProvider(LLMProvider):
    name = "fake"

    async def health(self):
        return ProviderHealth(True, "ok")

    async def list_models(self):
        return ["fake"]

    async def complete(self, request: CompletionRequest):
        assert "FOLLOW-UP DRAFT MODE" in request.system
        return '''{
          "action": "send_reply",
          "mailbox_id": "attacker",
          "message_id": "attacker",
          "recipient": "wrong@example.com",
          "subject": "Re: Angebot",
          "body": "Guten Tag, ich wollte freundlich nachfragen, ob es hierzu bereits einen Stand gibt.",
          "confidence": 0.96,
          "reason": "Follow-up"
        }'''


def test_followup_is_local_draft_and_is_cryptographically_signed(tmp_path: Path):
    agent = MailAgent()
    profile = AgentProfile(owner_id="owner", agent_name="Nova", usage_type=UsageType.WORK, autonomy_mode=AutonomyMode.AUTONOMOUS)
    message = MailMessageContext(mailbox_id="mb", message_id="m1", thread_id="t1", sender="person@example.com", recipients=["owner@example.com"], subject="Angebot", body="Bitte um Rückmeldung")
    manager = IdentityManager(tmp_path / "identity")
    identity = manager.create(owner_id="owner", agent_name="Nova", usage_type="work")
    proposal = asyncio.run(agent.draft_follow_up(profile=profile, provider=FollowUpProvider(), model="fake", message=message, identity=identity, sign_payload=manager.sign, rationale="Warte seit vier Tagen"))
    assert proposal.action == MailActionType.CREATE_DRAFT
    assert proposal.mailbox_id == "mb"
    assert proposal.message_id == "m1"
    assert proposal.thread_id == "t1"
    assert proposal.recipient == "person@example.com"
    assert proposal.metadata["drafted_from_action"] == MailActionType.SEND_REPLY.value
    assert proposal.metadata["follow_up_draft"] is True
    assert_mandatory_agent_signature(proposal.body or "", identity)


class FakeGoogleClient:
    def __init__(self):
        self.calls = []

    async def modify_message(self, message_id, **kwargs):
        self.calls.append((message_id, kwargs))


class FakeExecutor:
    def __init__(self, client):
        self.client = client
        self.mailbox_lookup = lambda mailbox_id: {"mailbox_id": mailbox_id, "connector": "gmail_api"}

    async def _google_client(self, mailbox):
        return self.client


def test_mark_read_undo_is_capability_scoped_and_restores_unread(tmp_path: Path):
    mail_store = MailStore(tmp_path / "mail.db")
    mail_store.upsert_messages([StoredMessage(mailbox_id="mb", uid=1, internet_message_id="<1@x>", thread_key="t1", sender="a@example.com", recipients=["owner@example.com"], subject="Subject", sent_at=None, body_text="body", seen=True, remote_id="r1", connector="gmail_api")])
    conversations = ConversationStore(tmp_path / "conversations.db")
    undo = conversations.create_undo(mailbox_id="mb", message_id="r1", thread_id="t1", action="mark_read", payload={"source":{"remote_id":"r1","connector":"gmail_api"},"execution":{"action":"mark_read"}}, ttl_seconds=30)
    client = FakeGoogleClient()
    service = UndoService(conversation_store=conversations, action_executor=FakeExecutor(client), mail_store=mail_store)
    result = asyncio.run(service.undo(undo["token"]))
    assert client.calls == [("r1", {"add_label_ids": ["UNREAD"]})]
    assert mail_store.get_message("mb", "r1")["seen"] is False
    assert result["resync_required"] is False
    assert conversations.get_undo(undo["token"])["status"] == "completed"


def test_available_undo_list_never_exposes_payload(tmp_path: Path):
    store = ConversationStore(tmp_path / "conversations.db")
    store.create_undo(mailbox_id="mb", message_id="r1", thread_id="t1", action="archive", payload={"source":{"remote_id":"r1"},"secret":"must-stay-internal"}, ttl_seconds=30)
    public = store.list_available_undo()
    assert public and public[0]["action"] == "archive"
    assert "payload" not in public[0]
    assert "payload_json" not in public[0]
