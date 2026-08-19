"""Privacy-minimized reports for side-effect-free MAIL-AGENT simulations."""

from __future__ import annotations

import json
import threading
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RESULT_KEYS = {
    "message_id",
    "thread_id",
    "sender",
    "subject",
    "action",
    "original_action",
    "category",
    "priority",
    "confidence",
    "needs_reply",
    "rule_mode",
    "matched_rule",
    "policy_allowed",
    "requires_approval",
    "risk",
    "planned_artifacts",
    "simulated_outcome",
    "reason",
    "error",
    "trace_id",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


class ShadowReportStore:
    """Append-only local reports that never store mail bodies, prompts or credentials."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @staticmethod
    def sanitize_result(result: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in result.items():
            if key not in _RESULT_KEYS or value is None:
                continue
            if key == "planned_artifacts":
                clean[key] = [
                    _text(item, 64)
                    for item in list(value or [])[:8]
                    if _text(item, 64)
                ]
            elif key in {"confidence"}:
                clean[key] = max(0.0, min(float(value), 1.0))
            elif key in {"needs_reply", "policy_allowed", "requires_approval"}:
                clean[key] = bool(value)
            elif key in {"reason", "error"}:
                clean[key] = _text(value, 800)
            elif key == "subject":
                clean[key] = _text(value, 500)
            elif key in {"message_id", "thread_id", "sender", "matched_rule"}:
                clean[key] = _text(value, 320)
            else:
                clean[key] = _text(value, 96)
        return clean

    def save_report(
        self,
        *,
        run_id: str,
        mailbox_id: str,
        requested: int,
        results: list[dict[str, Any]],
        started_at: str,
        finished_at: str | None = None,
        trigger: str = "historical_replay",
    ) -> dict[str, Any]:
        sanitized = [self.sanitize_result(item) for item in results]
        outcomes = Counter(
            str(item.get("simulated_outcome") or "unknown") for item in sanitized
        )
        report = {
            "kind": "shadow_report",
            "run_id": _text(run_id, 96),
            "mailbox_id": _text(mailbox_id, 160),
            "trigger": _text(trigger, 64),
            "started_at": _text(started_at, 80),
            "finished_at": _text(finished_at or _now(), 80),
            "requested": max(0, int(requested)),
            "analyzed": sum(1 for item in sanitized if not item.get("error")),
            "errors": sum(1 for item in sanitized if item.get("error")),
            "side_effects": 0,
            "outcomes": dict(sorted(outcomes.items())),
            "results": sanitized,
        }
        self._append(report)
        return report

    def recent_reports(
        self,
        limit: int = 10,
        *,
        mailbox_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if not self.path.exists():
            return []
        items: deque[dict[str, Any]] = deque(maxlen=max(100, limit * 8))
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            item = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if item.get("kind") != "shadow_report":
                            continue
                        if mailbox_id and item.get("mailbox_id") != mailbox_id:
                            continue
                        items.append(item)
            except OSError:
                return []
        return list(reversed(items))[:limit]

    def _append(self, item: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
