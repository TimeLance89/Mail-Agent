from __future__ import annotations

import re
from collections import Counter
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
        try:
            health = await provider.health()
        except Exception:
            return False
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
        try:
            health = await provider.health()
        except Exception:
            return None
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
        primary = self.primary()
        if role in _FORCED_PRIMARY_ROLES.get():
            return RouteChoice(role, primary.provider_name, primary.model, "runtime_fallback")

        routing = self.settings()
        # Overrides are retained while automatic mode is active, but deliberately dormant. This
        # lets the owner switch back to Expert without losing configuration while keeping Automatic
        # genuinely automatic.
        if routing.mode == "expert":
            endpoint = getattr(routing, role, None)
            if endpoint is not None and await self._endpoint_available(endpoint):
                return RouteChoice(role, endpoint.provider, endpoint.model, "expert_override")

        if routing.mode == "automatic" and role == "classification":
            local = await self._auto_local()
            if local is not None:
                return RouteChoice(role, local.provider, local.model, "automatic_local")
        return RouteChoice(role, primary.provider_name, primary.model, "primary_fallback")


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
    @staticmethod
    def _token_coverage(sources: dict[str, int]) -> str:
        known = {key for key, count in sources.items() if count and key in {"provider_reported", "estimated"}}
        if known == {"provider_reported"}:
            return "provider_reported"
        if known == {"estimated"}:
            return "estimated"
        if known:
            return "mixed"
        return "unknown"

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
        result["token_sources"] = sources
        result["token_coverage"] = self._token_coverage(sources)
        return result

    def calendar_day_summary(self) -> dict[str, Any]:
        """Return a self-consistent UTC calendar-day summary, not a rolling 24h window."""

        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM usage_events WHERE at>=? ORDER BY at DESC",
                    (start,),
                ).fetchall()
            ]

        task_counts: Counter[str] = Counter()
        route_counts: Counter[str] = Counter()
        provider_counts: Counter[str] = Counter()
        token_sources: Counter[str] = Counter()
        prompt_total = 0
        completion_total = 0
        known_token_events = 0
        duration_total = 0
        duration_count = 0
        avoided = 0
        estimated_avoided = 0
        llm_calls = 0

        for row in rows:
            calls = int(row.get("llm_calls") or 0)
            llm_calls += calls
            task_counts[str(row.get("task_class") or "unknown")] += calls
            route_counts[str(row.get("route") or "unknown")] += 1
            if row.get("provider"):
                provider_counts[str(row["provider"])] += calls
            if row.get("prompt_tokens") is not None:
                prompt_total += int(row["prompt_tokens"])
                completion_total += int(row.get("completion_tokens") or 0)
                known_token_events += 1
                if calls > 0:
                    token_sources[str(row.get("token_source") or "unknown")] += 1
            if row.get("duration_ms") is not None:
                duration_total += int(row["duration_ms"])
                duration_count += 1
            avoided += int(row.get("avoided_codex") or 0)
            estimated_avoided += int(row.get("estimated_tokens_avoided") or 0)

        decision_events = len(rows)
        sources = dict(token_sources)
        return {
            "period_days": 1,
            "decision_events": decision_events,
            "today_events": decision_events,
            "llm_calls": llm_calls,
            "today_llm_calls": llm_calls,
            "routes": dict(route_counts),
            "providers": dict(provider_counts),
            "tasks": dict(task_counts),
            "codex_calls_avoided": avoided,
            "codex_avoidance_percent": round((avoided / decision_events) * 100, 1) if decision_events else 0.0,
            "prompt_tokens": prompt_total if known_token_events else None,
            "completion_tokens": completion_total if known_token_events else None,
            "token_coverage": self._token_coverage(sources),
            "token_sources": sources,
            "avg_duration_ms": round(duration_total / duration_count) if duration_count else None,
            "estimated_tokens_avoided": estimated_avoided,
        }


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
        routing = self.router.settings()
        expert_configured = routing.mode == "expert" and getattr(routing, role, None) is not None
        fallback_used = False
        try:
            analysis = await super().analyze(**kwargs)
        except Exception:
            if not expert_configured:
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
        routing = self.router.settings()
        expert_configured = routing.mode == "expert" and routing.draft is not None
        try:
            return await super().draft_follow_up(**kwargs)
        except Exception:
            if not expert_configured:
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
        clear_trace = kwargs.get("stage") == "llm" and kwargs.get("status") == "completed"
        if clear_trace:
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
        try:
            return original_record(*args, **kwargs)
        finally:
            if clear_trace:
                _DECISION_TRACE.set(None)

    activity.record = record_with_real_origin  # type: ignore[method-assign]
    activity._release_0161_trace_installed = True  # type: ignore[attr-defined]
