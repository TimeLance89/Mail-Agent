from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from mail_agent_core.providers import CodexCliProvider, _hidden_process_creationflags


class CodexUsageReader:
    """Read only provider-reported usage from the official Codex app-server protocol."""

    def __init__(self, provider: CodexCliProvider):
        self.provider = provider

    @staticmethod
    def _normalize_rate_window(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        used = value.get("usedPercent")
        used_percent = float(used) if isinstance(used, (int, float)) else None
        return {
            "used_percent": used_percent,
            "remaining_percent": (
                round(max(0.0, 100.0 - used_percent), 2)
                if used_percent is not None
                else None
            ),
            "window_duration_minutes": value.get("windowDurationMins"),
            "resets_at": value.get("resetsAt"),
            "source": "provider_reported",
        }

    @classmethod
    def _normalize_rate_limits(cls, payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        snapshot = payload.get("rateLimits") or payload.get("rate_limits") or payload
        if not isinstance(snapshot, dict):
            return None
        return {
            "limit_id": snapshot.get("limitId"),
            "limit_name": snapshot.get("limitName"),
            "primary": cls._normalize_rate_window(snapshot.get("primary")),
            "secondary": cls._normalize_rate_window(snapshot.get("secondary")),
            "plan_type": snapshot.get("planType"),
            "rate_limit_reached_type": snapshot.get("rateLimitReachedType"),
            "source": "provider_reported",
        }

    @staticmethod
    async def _write(proc: Any, message: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise RuntimeError("Codex app-server stdin is unavailable")
        proc.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await proc.stdin.drain()

    @staticmethod
    async def _next_response(proc: Any, wanted_id: str, deadline: float) -> dict[str, Any] | None:
        if proc.stdout is None:
            return None
        while time.monotonic() < deadline:
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=max(0.1, deadline - time.monotonic())
                )
            except TimeoutError:
                return None
            if not line:
                return None
            try:
                event = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("id") == wanted_id:
                return event
        return None

    async def _rpc(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
        try:
            command = self.provider._command("app-server")  # noqa: SLF001
        except Exception as exc:
            return None, None, str(exc)

        proc: Any | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_hidden_process_creationflags(),
            )
            deadline = time.monotonic() + 10.0
            await self._write(
                proc,
                {
                    "id": "mail-agent-init",
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "mail_agent",
                            "title": "MAIL-AGENT",
                            "version": "0.19.1",
                        }
                    },
                },
            )
            init = await self._next_response(proc, "mail-agent-init", deadline)
            if init is None:
                return None, None, "Codex app-server initialize timed out"
            if init.get("error"):
                return None, None, f"Codex app-server initialize failed: {init['error']}"[:500]

            # Official protocol ordering: acknowledge initialization only after the initialize
            # response, then issue account requests on the initialized connection.
            await self._write(proc, {"method": "initialized"})
            await self._write(
                proc,
                {"id": "mail-agent-rate", "method": "account/rateLimits/read", "params": {}},
            )
            await self._write(
                proc,
                {"id": "mail-agent-usage", "method": "account/usage/read", "params": {}},
            )

            responses: dict[str, dict[str, Any]] = {}
            errors: list[str] = []
            while time.monotonic() < deadline and len(responses) < 2:
                if proc.stdout is None:
                    break
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=max(0.1, deadline - time.monotonic())
                    )
                except TimeoutError:
                    break
                if not line:
                    break
                try:
                    event = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                request_id = event.get("id") if isinstance(event, dict) else None
                if request_id not in {"mail-agent-rate", "mail-agent-usage"}:
                    continue
                responses[str(request_id)] = event
                if event.get("error"):
                    errors.append(str(event["error"])[:500])

            rate_event = responses.get("mail-agent-rate") or {}
            usage_event = responses.get("mail-agent-usage") or {}
            rate = rate_event.get("result") if isinstance(rate_event.get("result"), dict) else None
            usage = usage_event.get("result") if isinstance(usage_event.get("result"), dict) else None
            if "mail-agent-rate" not in responses:
                errors.append("account/rateLimits/read timed out")
            if "mail-agent-usage" not in responses:
                errors.append("account/usage/read timed out")
            return rate, usage, "; ".join(errors) or None
        except Exception as exc:
            return None, None, str(exc)
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    async def snapshot(self) -> dict[str, Any]:
        health = await self.provider.health()
        if not health.available:
            return {
                "available": False,
                "source": "unknown",
                "detail": health.detail,
                "rate_limits": None,
                "usage": None,
            }
        rate, usage, error = await self._rpc()
        normalized_rate = self._normalize_rate_limits(rate)
        source = "provider_reported" if normalized_rate or usage else "unknown"
        return {
            "available": True,
            "source": source,
            "detail": error or health.detail,
            "rate_limits": normalized_rate,
            "usage": usage if isinstance(usage, dict) else None,
        }
