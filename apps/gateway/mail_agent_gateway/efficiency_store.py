from __future__ import annotations

from typing import Literal

from .adaptive_intelligence import AdaptiveSignalStore, _safe_model, utc_now


class EfficiencySignalStore(AdaptiveSignalStore):
    """0.16 telemetry store with explicit avoided-token accounting."""

    def __init__(self, path):
        super().__init__(path)
        with self._connect() as conn:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(usage_events)")}
            if "estimated_tokens_avoided" not in columns:
                conn.execute(
                    "ALTER TABLE usage_events ADD COLUMN estimated_tokens_avoided INTEGER"
                )

    def record_usage(
        self,
        *,
        task_class: str,
        route: str,
        provider: str | None,
        model: str | None,
        llm_calls: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        token_source: Literal["provider_reported", "estimated", "unknown"],
        duration_ms: int | None,
        avoided_codex: bool,
        decision_origin: str,
    ) -> None:
        # In the legacy adaptive layer, a deterministic skip passes the would-be prompt estimate in
        # prompt_tokens. Preserve that useful baseline as savings, but never report it as consumed.
        estimated_avoided = None
        actual_prompt = prompt_tokens
        actual_completion = completion_tokens
        if int(llm_calls) == 0:
            actual_prompt = 0
            actual_completion = 0
            if avoided_codex and prompt_tokens is not None:
                estimated_avoided = max(0, int(prompt_tokens))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events(
                    at, task_class, route, provider, model, llm_calls, prompt_tokens,
                    completion_tokens, token_source, duration_ms, avoided_codex, decision_origin,
                    estimated_tokens_avoided
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    str(task_class)[:80],
                    str(route)[:80],
                    str(provider)[:40] if provider else None,
                    _safe_model(model) if model else None,
                    max(0, int(llm_calls)),
                    max(0, int(actual_prompt)) if actual_prompt is not None else None,
                    max(0, int(actual_completion)) if actual_completion is not None else None,
                    token_source,
                    max(0, int(duration_ms)) if duration_ms is not None else None,
                    1 if avoided_codex else 0,
                    str(decision_origin)[:80],
                    estimated_avoided,
                ),
            )

    def summary(self, *, days: int = 7):
        result = super().summary(days=days)
        from datetime import UTC, datetime, timedelta

        since = (datetime.now(UTC) - timedelta(days=max(1, min(int(days), 3650)))).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(estimated_tokens_avoided), 0) AS saved
                FROM usage_events WHERE at>=?
                """,
                (since,),
            ).fetchone()
        result["estimated_tokens_avoided"] = int(row["saved"] if row else 0)
        return result
