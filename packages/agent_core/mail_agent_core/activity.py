"""Local, privacy-minimized observability for MAIL-AGENT."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SAFE_DATA_KEYS = {
    "provider",
    "model",
    "trigger",
    "connector",
    "messages_synced",
    "thread_context_messages",
    "brain_chars",
    "action",
    "original_action",
    "category",
    "priority",
    "confidence",
    "confidence_threshold",
    "needs_reply",
    "rule_mode",
    "allowed",
    "requires_approval",
    "risk",
    "approval_id",
    "draft_id",
    "execution_status",
    "artifact",
    "outcome",
    "execution_mode",
    "shadow_run_id",
    "planned_artifacts",
    "side_effects",
    "matched_rule",
}
_FORBIDDEN_KEY_PARTS = {
    "body",
    "prompt",
    "content",
    "secret",
    "token",
    "password",
    "memory",
    "soul",
    "brain_context",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_text(value: Any, limit: int = 800) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


class AgentActivityStore:
    """Append-only local trace store.

    It deliberately stores metadata and decisions, never mail bodies, prompts, credentials,
    SOUL/MEMORY contents or provider tokens. Observability failures are non-fatal by design.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def begin_message(
        self,
        *,
        mailbox_id: str,
        message_id: str,
        thread_id: str | None,
        sender: str,
        subject: str,
        provider: str,
        model: str,
        trigger: str,
    ) -> str:
        trace_id = "trace_" + uuid.uuid4().hex
        self.record(
            trace_id=trace_id,
            stage="queued",
            status="running",
            detail="Nach der Synchronisierung für die Agentenbearbeitung eingeplant.",
            mailbox_id=mailbox_id,
            message_id=message_id,
            thread_id=thread_id,
            sender=sender,
            subject=subject,
            data={"provider": provider, "model": model, "trigger": trigger},
        )
        return trace_id

    def record_sync(
        self,
        *,
        mailbox_id: str,
        status: str,
        detail: str,
        connector: str | None = None,
        messages_synced: int | None = None,
    ) -> str:
        trace_id = "sync_" + uuid.uuid4().hex
        self.record(
            trace_id=trace_id,
            stage="sync",
            status=status,
            detail=detail,
            mailbox_id=mailbox_id,
            message_id=None,
            thread_id=None,
            sender=None,
            subject="Postfach-Synchronisierung",
            data={"connector": connector, "messages_synced": messages_synced},
        )
        self.finish(
            trace_id,
            outcome="sync_completed" if status == "completed" else "error",
            reason=detail,
        )
        return trace_id

    def record(
        self,
        *,
        trace_id: str,
        stage: str,
        status: str,
        detail: str = "",
        duration_ms: int | None = None,
        mailbox_id: str | None = None,
        message_id: str | None = None,
        thread_id: str | None = None,
        sender: str | None = None,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "kind": "trace_step",
            "trace_id": _safe_text(trace_id, 96),
            "at": _utc_now(),
            "stage": _safe_text(stage, 64),
            "status": _safe_text(status, 40),
            "detail": _safe_text(detail),
            "duration_ms": max(0, int(duration_ms)) if duration_ms is not None else None,
            "mailbox_id": _safe_text(mailbox_id, 160) or None,
            "message_id": _safe_text(message_id, 320) or None,
            "thread_id": _safe_text(thread_id, 320) or None,
            "sender": _safe_text(sender, 320).lower() or None,
            "subject": _safe_text(subject, 500) or None,
            "data": self._sanitize_data(data or {}),
        }
        self._append(event)

    def finish(self, trace_id: str, *, outcome: str, reason: str = "") -> None:
        self.record(
            trace_id=trace_id,
            stage="finished",
            status="completed" if outcome != "error" else "failed",
            detail=reason,
            data={"outcome": outcome},
        )

    def recent_traces(
        self,
        limit: int = 25,
        *,
        mailbox_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        events = self._read_recent(max(400, limit * 24))
        traces: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for event in events:
            if event.get("kind") != "trace_step":
                continue
            trace_id = str(event.get("trace_id") or "")
            if not trace_id:
                continue
            trace = traces.get(trace_id)
            if trace is None:
                trace = {
                    "trace_id": trace_id,
                    "mailbox_id": event.get("mailbox_id"),
                    "message_id": event.get("message_id"),
                    "thread_id": event.get("thread_id"),
                    "sender": event.get("sender"),
                    "subject": event.get("subject"),
                    "provider": (event.get("data") or {}).get("provider"),
                    "model": (event.get("data") or {}).get("model"),
                    "trigger": (event.get("data") or {}).get("trigger"),
                    "started_at": event.get("at"),
                    "last_at": event.get("at"),
                    "status": "running",
                    "outcome": None,
                    "reason": "",
                    "steps": [],
                }
                traces[trace_id] = trace
                order.append(trace_id)
            for key in ("mailbox_id", "message_id", "thread_id", "sender", "subject"):
                if trace.get(key) is None and event.get(key) is not None:
                    trace[key] = event.get(key)
            data = event.get("data") or {}
            trace["provider"] = trace.get("provider") or data.get("provider")
            trace["model"] = trace.get("model") or data.get("model")
            trace["trigger"] = trace.get("trigger") or data.get("trigger")
            trace["last_at"] = event.get("at") or trace["last_at"]
            trace["steps"].append(
                {
                    "at": event.get("at"),
                    "stage": event.get("stage"),
                    "status": event.get("status"),
                    "detail": event.get("detail"),
                    "duration_ms": event.get("duration_ms"),
                    "data": data,
                }
            )
            if event.get("stage") == "finished":
                trace["status"] = event.get("status") or "completed"
                trace["outcome"] = data.get("outcome")
                trace["reason"] = event.get("detail") or ""
            elif trace["status"] == "running" and event.get("status") == "failed":
                trace["status"] = "failed"
                trace["reason"] = event.get("detail") or ""

        result = [traces[trace_id] for trace_id in order]
        if mailbox_id:
            result = [item for item in result if item.get("mailbox_id") == mailbox_id]
        result.sort(key=lambda item: str(item.get("last_at") or ""), reverse=True)
        return result[:limit]

    def summary(self, *, mailbox_id: str | None = None) -> dict[str, Any]:
        traces = self.recent_traces(100, mailbox_id=mailbox_id)
        mail_traces = [item for item in traces if item.get("message_id")]
        llm_times = [
            int(step["duration_ms"])
            for trace in mail_traces
            for step in trace.get("steps", [])
            if step.get("stage") == "llm" and step.get("duration_ms") is not None
        ]
        outcomes: dict[str, int] = {}
        for trace in mail_traces:
            outcome = str(trace.get("outcome") or trace.get("status") or "running")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return {
            "trace_count": len(mail_traces),
            "sync_trace_count": len(traces) - len(mail_traces),
            "running": sum(1 for item in mail_traces if item.get("status") == "running"),
            "failed": sum(1 for item in mail_traces if item.get("status") == "failed"),
            "outcomes": outcomes,
            "avg_llm_ms": round(sum(llm_times) / len(llm_times)) if llm_times else None,
            "latest_at": traces[0].get("last_at") if traces else None,
        }

    def _sanitize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in data.items():
            key_text = str(key)
            lowered = key_text.lower()
            if key_text not in _SAFE_DATA_KEYS:
                continue
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                continue
            if value is None or isinstance(value, (bool, int, float)):
                result[key_text] = value
            elif isinstance(value, (list, tuple)):
                result[key_text] = [_safe_text(item, 96) for item in list(value)[:8]]
            else:
                result[key_text] = _safe_text(value, 500)
        return result

    def _append(self, event: dict[str, Any]) -> None:
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            return

    def _read_recent(self, limit: int) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        items: deque[dict[str, Any]] = deque(maxlen=max(1, limit))
        try:
            with self._lock, self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        items.append(item)
        except OSError:
            return []
        return list(items)
