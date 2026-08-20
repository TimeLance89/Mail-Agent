from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from mail_agent_core.models import MailCategory
from mail_agent_core.providers import ProviderHealth

from mail_agent_gateway.adaptive_intelligence import (
    ModelRoutingRequest,
    ModelRoutingSettings,
    OwnerProfileCandidate,
)
from mail_agent_gateway.conversation_store import ConversationStore
from mail_agent_gateway.release_audit_fixes import (
    ReleaseEfficiencySignalStore,
    ReleaseModelRouter,
    ReleaseOwnerProfileStore,
    ReleasePreLLMClassifier,
    _DECISION_TRACE,
    install_release_runtime_fixes,
    normalize_sender_address,
    sender_pattern_matches,
)


class StateStore:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

    def write(self, value):
        self.value = value


class FakeProvider:
    name = "fake"

    def __init__(self, models=None, *, available=True, list_error=False):
        self.models = list(models or [])
        self.available = available
        self.list_error = list_error

    async def health(self):
        return ProviderHealth(self.available, "ok" if self.available else "down")

    async def list_models(self):
        if self.list_error:
            raise RuntimeError("catalog unavailable")
        return self.models

    async def complete(self, request):  # pragma: no cover - routing tests never call generation
        raise AssertionError("generation should not be called")


def _routing_state(routing=None):
    return StateStore(
        {
            "onboarding_completed": True,
            "configuration": {
                "provider": "codex",
                "model": "gpt-main",
                "model_routing": routing or {"mode": "automatic"},
            },
        }
    )


def test_display_name_sender_normalizes_to_owner_confirmed_address(tmp_path: Path):
    assert normalize_sender_address("News Team <NEWS@example.com>") == "news@example.com"
    assert sender_pattern_matches("news@example.com", "News Team <news@example.com>")
    assert sender_pattern_matches("@example.com", "News Team <news@example.com>")

    conversations = ConversationStore(tmp_path / "conversations.db")
    conversations.decide_pattern("mb", "news@example.com", "newsletter", status="accepted")
    signals = ReleaseEfficiencySignalStore(tmp_path / "adaptive.db")
    classifier = ReleasePreLLMClassifier(conversations, signals)
    assert (
        classifier._accepted_sender_category("mb", "News Team <news@example.com>")
        == MailCategory.NEWSLETTER
    )


@pytest.mark.asyncio
async def test_automatic_local_routing_prefers_smallest_discoverable_model():
    state = _routing_state()
    router = ReleaseModelRouter(
        state,
        {
            "ollama": FakeProvider(["qwen:14b", "qwen:7b", "tiny:3b"]),
            "codex": FakeProvider(["gpt-main"]),
        },
    )
    route = await router.route("classification")
    assert route.provider_name == "ollama"
    assert route.model == "tiny:3b"
    assert route.source == "automatic_local"


@pytest.mark.asyncio
async def test_retained_expert_override_is_dormant_while_mode_is_automatic():
    state = _routing_state(
        {
            "mode": "automatic",
            "normal": {"provider": "ollama", "model": "tiny:3b"},
        }
    )
    router = ReleaseModelRouter(
        state,
        {
            "ollama": FakeProvider(["tiny:3b"]),
            "codex": FakeProvider(["gpt-main"]),
        },
    )
    route = await router.route("normal")
    assert (route.provider_name, route.model, route.source) == (
        "codex",
        "gpt-main",
        "primary_fallback",
    )


@pytest.mark.asyncio
async def test_unverifiable_or_missing_expert_model_falls_back_to_primary():
    routing = {
        "mode": "expert",
        "normal": {"provider": "ollama", "model": "missing:99b"},
    }
    state = _routing_state(routing)
    router = ReleaseModelRouter(
        state,
        {
            "ollama": FakeProvider(["tiny:3b"]),
            "codex": FakeProvider(["gpt-main"]),
        },
    )
    route = await router.route("normal")
    assert (route.provider_name, route.model, route.source) == (
        "codex",
        "gpt-main",
        "primary_fallback",
    )

    router = ReleaseModelRouter(
        state,
        {
            "ollama": FakeProvider(list_error=True),
            "codex": FakeProvider(["gpt-main"]),
        },
    )
    route = await router.route("normal")
    assert route.source == "primary_fallback"


def test_owner_profile_store_rejects_obvious_pii_and_discards_model_rationale(tmp_path: Path):
    store = ReleaseOwnerProfileStore(tmp_path / "owner-profile.json")
    store.set_consent(True)
    safe = OwnerProfileCandidate(
        key="response_length",
        value="kurz und direkt",
        confidence=0.9,
        evidence_count=2,
        rationale="Copied evidence that should never persist",
        source_refs=["src_a", "src_b"],
    )
    unsafe = OwnerProfileCandidate(
        key="closing",
        value="Kontakt über owner@example.com",
        confidence=0.9,
        evidence_count=2,
        source_refs=["src_a", "src_b"],
    )
    result = store.save_preview([safe, unsafe], sample_count=3)
    assert len(result["preview"]) == 1
    assert result["preview"][0]["value"] == "kurz und direkt"
    assert "Copied evidence" not in result["preview"][0]["rationale"]
    assert "owner@example.com" not in store.path.read_text(encoding="utf-8")


def test_usage_summary_distinguishes_provider_reported_estimated_and_mixed(tmp_path: Path):
    store = ReleaseEfficiencySignalStore(tmp_path / "adaptive.db")
    store.record_usage(
        task_class="classification",
        route="local_triage",
        provider="ollama",
        model="tiny:3b",
        llm_calls=1,
        prompt_tokens=100,
        completion_tokens=10,
        token_source="provider_reported",
        duration_ms=12,
        avoided_codex=True,
        decision_origin="local_triage",
    )
    assert store.summary(days=7)["token_coverage"] == "provider_reported"
    store.record_usage(
        task_class="normal_analysis",
        route="normal",
        provider="codex",
        model="gpt-main",
        llm_calls=1,
        prompt_tokens=200,
        completion_tokens=20,
        token_source="estimated",
        duration_ms=20,
        avoided_codex=False,
        decision_origin="llm",
    )
    summary = store.summary(days=7)
    assert summary["token_coverage"] == "mixed"
    assert summary["token_sources"] == {"estimated": 1, "provider_reported": 1}


def test_activity_trace_reports_deterministic_origin_not_fake_codex_llm():
    class Activity:
        def __init__(self):
            self.events = []

        def record(self, *args, **kwargs):
            self.events.append(kwargs)
            return kwargs

    class Runtime:
        def __init__(self):
            self.activity = Activity()

    runtime = Runtime()
    install_release_runtime_fixes(runtime)
    _DECISION_TRACE.set(
        {
            "decision_origin": "deterministic",
            "llm_called": False,
            "decision_provenance": ["header:bulk"],
        }
    )
    runtime.activity.record(
        trace_id="trace",
        stage="llm",
        status="completed",
        detail="codex / gpt-main hat die Mail analysiert.",
        duration_ms=123,
        data={"provider": "codex", "model": "gpt-main"},
    )
    event = runtime.activity.events[-1]
    assert event["stage"] == "pre_llm"
    assert event["duration_ms"] == 0
    assert event["data"]["llm_called"] is False
    assert event["data"]["provider"] is None
    assert "codex" not in event["detail"].lower()
    assert _DECISION_TRACE.get() is None


def test_adaptive_ui_contract_has_truthful_usage_and_preserves_overrides():
    source = Path("apps/web/adaptive-intelligence-ui.js").read_text(encoding="utf-8")
    assert "today.today_llm_calls??today.llm_calls" in source
    assert "local.token_coverage" in source
    assert "Codex Tokens gesamt" in source
    assert "account.totalTokens" in source
    assert "routing[role]=endpoint(state.status?.model_routing,role)" in source
    assert "new MutationObserver" not in source


@pytest.mark.asyncio
async def test_model_routing_api_returns_409_before_onboarding_and_preserves_overrides():
    from mail_agent_gateway import main_v16

    original_state = main_v16.model_router.state_store
    try:
        main_v16.model_router.state_store = StateStore({})
        request = ModelRoutingRequest(routing=ModelRoutingSettings(mode="automatic"))
        with pytest.raises(HTTPException) as caught:
            await main_v16.model_routing_update(request)
        assert caught.value.status_code == 409

        state = _routing_state(
            {
                "mode": "expert",
                "normal": {"provider": "ollama", "model": "tiny:3b"},
            }
        )
        main_v16.model_router.state_store = state
        result = await main_v16.model_routing_update(
            ModelRoutingRequest(routing=ModelRoutingSettings(mode="automatic"))
        )
        assert result["mode"] == "automatic"
        assert result["normal"] == {"provider": "ollama", "model": "tiny:3b"}
        assert state.read()["configuration"]["model_routing"]["normal"] == result["normal"]
    finally:
        main_v16.model_router.state_store = original_state
