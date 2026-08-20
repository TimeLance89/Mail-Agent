from __future__ import annotations

import re
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from typing import Any

from mail_agent_core.models import MailCategory

from . import adaptive_intelligence as adaptive_module
from .adaptive_intelligence import (
    AdaptiveMailAgent,
    ModelEndpoint,
    ModelRouter,
    OwnerProfileCandidate,
    OwnerProfileReview,
    OwnerProfileStore,
    PreLLMClassifier,
    RouteChoice,
)
from .efficiency_store import EfficiencySignalStore


_FORCED_PRIMARY_ROLES: ContextVar[frozenset[str]] = ContextVar(
    "mail_agent_forced_primary_roles", default=frozenset()
)
_DECISION_TRACE: ContextVar[dict[str, Any] | None] = ContextVar(
    "mail_agent_decision_trace", default=None
)

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)")
_MODEL_SIZE_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*[bB](?!\w)")


def normalize_sender_address(value: str) -> str:
    raw = str(value or "").strip().casefold()
    parsed = parseaddr(raw)[1].strip().casefold()
    return parsed or raw


def sender_pattern_matches(pattern: str, sender: str) -> bool:
    wanted_raw = str(pattern or "").strip().casefold()
    sender_address = normalize_sender_address(sender)
    if not wanted_raw or not sender_address:
        return False
    if wanted_raw.startswith("@"):
        return sender_address.endswith(wanted_raw)
    return normalize_sender_address(wanted_raw) == sender_address


class ReleasePreLLMClassifier(PreLLMClassifier):
    def _accepted_sender_category(self, mailbox_id: str, sender: str) -> MailCategory | None:
        normalized = normalize_sender_address(sender)
        try:
            with self.conversation_store._connect() as conn:  # noqa: SLF001
                row = conn.execute(
                    """
                    SELECT category FROM sender_pattern_decisions
                    WHERE mailbox_id=? AND sender=? AND status='accepted'
                    ORDER BY decided_at DESC LIMIT 1
                    """,
                    (mailbox_id, normalized),
                ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        try:
            return MailCategory(str(row["category"]))
        except Exception:
            return None


class ReleaseModelRouter(ModelRouter):
    @staticmethod
    def _model_score(model: str) -> tuple[int, float, str]:
        match = _MODEL_SIZE_RE.search(str(model or ""))
        if match:
            return (0, float(match.group(1)), str(model).casefold())
        lowered = str(model or "").casefold()
        if any(marker in lowered for marker in ("mini", "small", "tiny")):
            return (0, 0.5, lowered)
        return (1, float("inf"), lowered)

    async def _endpoint_available(self, endpoint: ModelEndpoint) -> bool:
        provider = self.providers.get(endpoint.provider)
        if provider is None:
            return False
        health = await provider.health()
        if not health.available:
            return False
        if endpoint.model == "default":
            return True
        try:
            models = await provider.list_models()
        except Exception:
            return False
        # An explicit expert override must be verifiable. Treat an unavailable/empty catalog as
        # unknown and fall back instead of gambling on a model name that can hard-fail a mail cycle.
        return bool(models) and endpoint.model in models

    async def _auto_local(self) -> ModelEndpoint | None:
        provider = self.providers.get("ollama")
        if provider is None:
            return None
        health = await provider.health()
        if not health.available:
            return None
        try:
            models = await provider.list_models()
        except Exception:
            return None
        if not models:
            return None
        chosen = min(models, key=self._model_score)
        return ModelEndpoint(provider="ollama", model=chosen)

    async def route(self, role: str) -> RouteChoice:
        if role in _FORCED_PRIMARY_ROLES.get():
            primary = self.primary()
            return RouteChoice(role, primary.provider_name, primary.model, "runtime_fallback")
        return await super().route(role)


class ReleaseOwnerProfileStore(OwnerProfileStore):
    @staticmethod
    def _safe_candidate(candidate: OwnerProfileCandidate) -> OwnerProfileCandidate | None:
        value = " ".join(str(candidate.value or "").split()).strip()
        if not value or len(value) > 160:
            return None
        if _EMAIL_RE.search(value) or _URL_RE.search(value) or _PHONE_RE.search(value):
            return None
        # Persist no model-written evidence prose. The reusable preference and non-content source
        # hashes are sufficient for owner review, while this removes an unnecessary path for raw
        # mail facts to leak into durable profile metadata.
        return candidate.model_copy(
            update={
                "value": value,
                "rationale": "Aus mehreren eigenen gesendeten Nachrichten als wiederkehrendes Muster abgeleitet.",
            }
        )

    @classmethod
    def _safe_candidates(cls, candidates: list[OwnerProfileCandidate]) -> list[OwnerProfileCandidate]:
        result: list[OwnerProfileCandidate] = []
        for candidate in candidates:
            safe = cls._safe_candidate(candidate)
            if safe is not None:
                result.append(safe)
        return result

    def save_preview(self, candidates: list[OwnerProfileCandidate], sample_count: int) -> dict[str, Any]:
        return super().save_preview(self._safe_candidates(candidates), sample_count)

    def activate(self, review: OwnerProfileReview) -> dict[str, Any]:
        safe = self._safe_candidates(review.candidates)
        return super().activate(OwnerProfileReview(candidates=safe))


class ReleaseEfficiencySignalStore(EfficiencySignalStore):
    def summary(self, *, days: int = 7):
        result = super().summary(days=days)
        since = (
            datetime.now(UTC) - timedelta(days=max(1, min(int(days), 3650)))
        ).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT token_source, COUNT(*) AS count
                FROM usage_events
                WHERE at>=? AND llm_calls>0 AND prompt_tokens IS NOT NULL
                GROUP BY token_source
                """,
                (since,),
            ).fetchall()
        sources = {str(row["token_source"]): int(row["count"]) for row in rows}
        known = {key for key, count in sources.items() if count and key in {"provider_reported", "estimated"}}
        if known == {"provider_reported"}:
            coverage = "provider_reported"
        elif known == {"estimated"}:
            coverage = "estimated"
        elif known:
            coverage = "mixed"
        else:
            coverage = "unknown"
        result["token_sources"] = sources
        result["token_coverage"] = coverage
        return result


class ReleaseAdaptiveMailAgent(AdaptiveMailAgent):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.router = ReleaseModelRouter(self.state_store, self.providers)
        self.preclassifier = ReleasePreLLMClassifier(
            kwargs["conversation_store"], kwargs["signal_store"]
        )

    async def analyze(self, **kwargs: Any):
        _DECISION_TRACE.set(None)
        message = kwargs.get("message")
        role = "complex" if message is not None and self._complex(message) else "normal"
        route = await self.router.route(role)
        fallback_used = False
        try:
            analysis = await super().analyze(**kwargs)
        except Exception:
            if route.source != "expert_override":
                raise
            token = _FORCED_PRIMARY_ROLES.set(frozenset({role}))
            fallback_used = True
            try:
                analysis = await super().analyze(**kwargs)
            finally:
                _FORCED_PRIMARY_ROLES.reset(token)

        metadata = dict(analysis.proposal.metadata or {})
        if fallback_used:
            metadata["routing_fallback"] = "primary_after_expert_failure"
            analysis.proposal.metadata = metadata
        _DECISION_TRACE.set(metadata)
        return analysis

    async def draft_follow_up(self, **kwargs: Any):
        route = await self.router.route("draft")
        try:
            return await super().draft_follow_up(**kwargs)
        except Exception:
            if route.source != "expert_override":
                raise
            token = _FORCED_PRIMARY_ROLES.set(frozenset({"draft"}))
            try:
                return await super().draft_follow_up(**kwargs)
            finally:
                _FORCED_PRIMARY_ROLES.reset(token)


def install_release_runtime_fixes(agent_runtime: Any) -> None:
    """Install narrow runtime presentation fixes without touching policy/executor authority."""

    adaptive_module._sender_pattern_matches = sender_pattern_matches

    activity = agent_runtime.activity
    if getattr(activity, "_release_0161_trace_installed", False):
        return
    original_record = activity.record

    def record_with_real_origin(*args: Any, **kwargs: Any):
        if kwargs.get("stage") == "llm" and kwargs.get("status") == "completed":
            trace = _DECISION_TRACE.get() or {}
            origin = str(trace.get("decision_origin") or "")
            data = dict(kwargs.get("data") or {})
            if origin == "deterministic":
                kwargs["stage"] = "pre_llm"
                kwargs["detail"] = "Deterministisch klassifiziert; kein LLM-Aufruf erforderlich."
                data.update({"provider": None, "model": None, "llm_called": False, "decision_origin": origin})
                kwargs["duration_ms"] = 0
                kwargs["data"] = data
            elif origin == "local_triage":
                provider = trace.get("routed_provider") or data.get("provider")
                model = trace.get("routed_model") or data.get("model")
                kwargs["stage"] = "local_triage"
                kwargs["detail"] = f"{provider or 'lokal'} / {model or 'default'} hat die Mail konservativ voranalysiert."
                data.update({"provider": provider, "model": model, "decision_origin": origin})
                kwargs["data"] = data
            elif origin == "llm":
                provider = trace.get("routed_provider") or data.get("provider")
                model = trace.get("routed_model") or data.get("model")
                kwargs["detail"] = f"{provider or 'LLM'} / {model or 'default'} hat die Mail analysiert."
                data.update({"provider": provider, "model": model, "decision_origin": origin})
                kwargs["data"] = data
        return original_record(*args, **kwargs)

    activity.record = record_with_real_origin  # type: ignore[method-assign]
    activity._release_0161_trace_installed = True  # type: ignore[attr-defined]
