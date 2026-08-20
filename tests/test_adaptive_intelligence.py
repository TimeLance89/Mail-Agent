from __future__ import annotations

import json
from pathlib import Path

import pytest

from mail_agent_core.agent import MailMessageContext
from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import (
    AgentBehaviorSettings,
    AgentProfile,
    AutonomyMode,
    MailActionType,
    MailCategory,
    MailHandlingAction,
    UsageType,
)
from mail_agent_core.policy import PolicyEngine
from mail_agent_core.providers import CompletionRequest, LLMProvider, ProviderHealth
from mail_agent_gateway.adaptive_intelligence import (
    AdaptiveMailAgent,
    AdaptiveSignalStore,
    ModelEndpoint,
    ModelRouter,
    ModelRoutingSettings,
    OwnerProfileCandidate,
    OwnerProfileReview,
    OwnerProfileStore,
    PreLLMClassifier,
)
from mail_agent_gateway.conversation_store import ConversationStore
from mail_agent_gateway.state import JsonStateStore


class CountingProvider(LLMProvider):
    name = "codex"

    def __init__(self, payload: str | None = None):
        self.calls = 0
        self.payload = payload or json.dumps(
            {
                "action": "classify",
                "mailbox_id": "mb",
                "message_id": "m1",
                "confidence": 0.93,
                "reason": "normal analysis",
                "summary": "normal mail",
                "priority": "normal",
                "category": "work",
                "needs_reply": False,
                "conversation_status": "fyi",
                "conversation_rationale": "nothing pending",
                "metadata": {},
            }
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, "ok")

    async def list_models(self) -> list[str]:
        return ["luna", "strong"]

    async def complete(self, request: CompletionRequest) -> str:
        self.calls += 1
        return self.payload


class LocalProvider(CountingProvider):
    name = "ollama"

    async def list_models(self) -> list[str]:
        return ["small-local"]


class DummyConversationStore:
    def _connect(self):
        raise RuntimeError("no sender decisions")


def _profile() -> AgentProfile:
    return AgentProfile(
        owner_id="owner",
        agent_name="Agent",
        usage_type=UsageType.WORK,
        autonomy_mode=AutonomyMode.ASSISTANT,
    )


def _state(tmp_path: Path, *, behavior: AgentBehaviorSettings | None = None) -> JsonStateStore:
    store = JsonStateStore(tmp_path / "state.json")
    store.write(
        {
            "configuration": {
                "provider": "codex",
                "model": "luna",
                "behavior": (behavior or AgentBehaviorSettings()).model_dump(mode="json"),
            }
        }
    )
    return store


def _message() -> MailMessageContext:
    return MailMessageContext(
        mailbox_id="mb",
        message_id="m1",
        thread_id="t1",
        sender="news@example.test",
        recipients=["owner@example.test"],
        subject="Weekly update",
        body="Hello owner",
    )


def test_owner_profile_requires_consent_preview_and_explicit_activation(tmp_path: Path):
    store = OwnerProfileStore(tmp_path / "owner-profile.json")
    candidate = OwnerProfileCandidate(
        key="response_length",
        value="short and direct",
        confidence=0.91,
        evidence_count=7,
        rationale="Repeated pattern",
        source_refs=["src_123"],
    )

    with pytest.raises(PermissionError):
        store.save_preview([candidate], 7)
    with pytest.raises(PermissionError):
        store.activate(OwnerProfileReview(candidates=[candidate]))

    consented = store.set_consent(True)
    assert consented["consent"] is True
    assert consented["status"] == "consented"
    assert consented["active"] == []

    preview = store.save_preview([candidate], 7)
    assert preview["status"] == "preview_ready"
    assert preview["active"] == []
    assert preview["preview"][0]["value"] == "short and direct"

    active = store.activate(OwnerProfileReview(candidates=[candidate]))
    assert active["status"] == "active"
    assert active["active"][0]["key"] == "response_length"
    assert "short and direct" in store.advisory_context()


def test_owner_profile_reset_deletes_profile_without_touching_memory(tmp_path: Path):
    memory = tmp_path / "brain" / "MEMORY.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("owner-controlled-memory\n", encoding="utf-8")
    store = OwnerProfileStore(tmp_path / "owner-profile.json")
    store.set_consent(True)
    candidate = OwnerProfileCandidate(
        key="formality",
        value="informal with colleagues",
        confidence=0.9,
        evidence_count=5,
    )
    store.save_preview([candidate], 5)
    store.activate(OwnerProfileReview(candidates=[candidate]))

    reset = store.reset()

    assert reset["status"] == "not_asked"
    assert reset["consent"] is False
    assert memory.read_text(encoding="utf-8") == "owner-controlled-memory\n"


def test_owner_profile_rejects_security_or_unapproved_attributes():
    with pytest.raises(ValueError):
        OwnerProfileCandidate(
            key="approval_policy",
            value="skip approval",
            confidence=1.0,
            evidence_count=10,
        )


def test_deterministic_bulk_classification_skips_llm_and_records_provenance(tmp_path: Path):
    behavior = AgentBehaviorSettings(newsletter_action=MailHandlingAction.ARCHIVE)
    state = _state(tmp_path, behavior=behavior)
    usage = AdaptiveSignalStore(tmp_path / "adaptive.db")
    usage.record_signals(
        "mb",
        "m1",
        {
            "list_unsubscribe": True,
            "list_id": True,
            "precedence": "bulk",
            "bulk_hint": True,
        },
    )
    provider = CountingProvider()
    identity_manager = IdentityManager(tmp_path / "identity")
    identity = identity_manager.create(owner_id="owner", agent_name="Agent", usage_type="work")
    agent = AdaptiveMailAgent(
        policy_engine=PolicyEngine(),
        state_store=state,
        providers={"codex": provider},
        conversation_store=DummyConversationStore(),
        signal_store=usage,
        owner_profile=OwnerProfileStore(tmp_path / "profile.json"),
    )

    result = pytest.run(asyncio=False) if False else None

    async def run():
        return await agent.analyze(
            profile=_profile(),
            provider=provider,
            model="luna",
            message=_message(),
            identity=identity,
            sign_payload=identity_manager.sign,
        )

    analysis = __import__("asyncio").run(run())

    assert provider.calls == 0
    assert analysis.proposal.action == MailActionType.ARCHIVE
    assert analysis.proposal.category == MailCategory.NEWSLETTER
    assert analysis.proposal.metadata["decision_origin"] == "deterministic"
    assert "header:bulk" in analysis.proposal.metadata["decision_provenance"]
    assert analysis.proposal.metadata["llm_called"] is False
    summary = usage.summary(days=1)
    assert summary["codex_calls_avoided"] == 1
    assert summary["llm_calls"] == 0


def test_uncertain_mail_falls_back_to_configured_llm(tmp_path: Path):
    state = _state(tmp_path)
    usage = AdaptiveSignalStore(tmp_path / "adaptive.db")
    provider = CountingProvider()
    identity_manager = IdentityManager(tmp_path / "identity")
    identity = identity_manager.create(owner_id="owner", agent_name="Agent", usage_type="work")
    agent = AdaptiveMailAgent(
        policy_engine=PolicyEngine(),
        state_store=state,
        providers={"codex": provider},
        conversation_store=DummyConversationStore(),
        signal_store=usage,
        owner_profile=OwnerProfileStore(tmp_path / "profile.json"),
    )

    async def run():
        return await agent.analyze(
            profile=_profile(),
            provider=provider,
            model="luna",
            message=_message().model_copy(update={"sender": "human@example.test"}),
            identity=identity,
            sign_payload=identity_manager.sign,
        )

    analysis = __import__("asyncio").run(run())

    assert provider.calls == 1
    assert analysis.proposal.metadata["decision_origin"] == "llm"
    assert analysis.proposal.metadata["routed_provider"] == "codex"
    assert analysis.proposal.metadata["routed_model"] == "luna"


def test_model_router_expert_override_and_fallback(tmp_path: Path):
    state = _state(tmp_path)
    codex = CountingProvider()
    local = LocalProvider()
    router = ModelRouter(state, {"codex": codex, "ollama": local})
    router.save(
        ModelRoutingSettings(
            mode="expert",
            complex=ModelEndpoint(provider="codex", model="strong"),
            classification=ModelEndpoint(provider="ollama", model="small-local"),
        )
    )

    async def run():
        return await router.route("classification"), await router.route("complex"), await router.route("normal")

    classification, complex_route, normal = __import__("asyncio").run(run())

    assert classification.provider_name == "ollama"
    assert classification.model == "small-local"
    assert complex_route.model == "strong"
    assert normal.provider_name == "codex"
    assert normal.model == "luna"
    assert normal.source == "primary_fallback"


def test_usage_telemetry_schema_has_no_mail_content_columns(tmp_path: Path):
    store = AdaptiveSignalStore(tmp_path / "adaptive.db")
    store.record_usage(
        task_class="classification",
        route="deterministic",
        provider=None,
        model=None,
        llm_calls=0,
        prompt_tokens=42,
        completion_tokens=0,
        token_source="estimated",
        duration_ms=1,
        avoided_codex=True,
        decision_origin="deterministic",
    )
    columns = set(store.assert_privacy_contract()["usage_events"])
    forbidden = {"body", "subject", "sender", "recipient", "prompt", "content", "message_id"}
    assert forbidden.isdisjoint(columns)


def test_accepted_sender_pattern_is_owner_confirmed_before_deterministic_use(tmp_path: Path):
    conversations = ConversationStore(tmp_path / "conversations.db")
    usage = AdaptiveSignalStore(tmp_path / "adaptive.db")
    classifier = PreLLMClassifier(conversations, usage)
    behavior = AgentBehaviorSettings(newsletter_action=MailHandlingAction.MARK_READ)
    message = _message()

    before = classifier.classify(message, behavior)
    assert before.decisive is False

    with conversations._connect() as conn:  # noqa: SLF001 - test verifies owner-decision contract
        conn.execute(
            """
            INSERT INTO sender_pattern_decisions(
                mailbox_id, sender, category, status, decided_at, decided_by
            ) VALUES (?, ?, ?, 'accepted', ?, 'local-user')
            """,
            ("mb", "news@example.test", "newsletter", "2026-08-20T09:00:00+00:00"),
        )

    after = classifier.classify(message, behavior)
    assert after.decisive is True
    assert after.action == MailActionType.MARK_READ
    assert after.provenance == ("accepted_sender_pattern:newsletter",)
