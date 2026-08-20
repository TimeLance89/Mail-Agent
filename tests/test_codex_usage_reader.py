from __future__ import annotations

import asyncio
import json

from mail_agent_gateway import codex_usage_reader as usage_module
from mail_agent_gateway.codex_usage_reader import CodexUsageReader


def test_codex_rate_limit_parser_marks_provider_reported_values():
    parsed = CodexUsageReader._normalize_rate_limits(
        {
            "rateLimits": {
                "limitId": "codex",
                "limitName": "Codex",
                "primary": {
                    "usedPercent": 73.5,
                    "windowDurationMins": 300,
                    "resetsAt": 1_787_200_000,
                },
                "secondary": {
                    "usedPercent": 22,
                    "windowDurationMins": 10080,
                    "resetsAt": 1_787_800_000,
                },
                "planType": "plus",
                "rateLimitReachedType": None,
            }
        }
    )

    assert parsed is not None
    assert parsed["source"] == "provider_reported"
    assert parsed["primary"]["used_percent"] == 73.5
    assert parsed["primary"]["remaining_percent"] == 26.5
    assert parsed["primary"]["window_duration_minutes"] == 300
    assert parsed["primary"]["resets_at"] == 1_787_200_000
    assert parsed["secondary"]["used_percent"] == 22.0


def test_codex_rate_limit_parser_never_invents_missing_percent_or_reset():
    parsed = CodexUsageReader._normalize_rate_limits(
        {
            "rateLimits": {
                "limitId": "codex",
                "limitName": "Codex",
                "primary": {"windowDurationMins": 300},
                "secondary": None,
            }
        }
    )

    assert parsed is not None
    assert parsed["primary"]["used_percent"] is None
    assert parsed["primary"]["remaining_percent"] is None
    assert parsed["primary"]["resets_at"] is None
    assert parsed["secondary"] is None


def test_codex_rate_limit_parser_returns_unknown_when_snapshot_is_not_structured():
    assert CodexUsageReader._normalize_rate_limits(None) is None
    assert CodexUsageReader._normalize_rate_limits("73%") is None
    assert CodexUsageReader._normalize_rate_limits([]) is None


def test_codex_app_server_waits_for_initialize_response_before_account_rpcs(monkeypatch):
    state = {"init_read": False, "writes": []}

    class FakeStdin:
        def write(self, raw: bytes):
            message = json.loads(raw.decode())
            state["writes"].append(message)
            if message.get("method") == "initialized" and not state["init_read"]:
                raise AssertionError("initialized sent before initialize response was read")

        async def drain(self):
            return None

    class FakeStdout:
        def __init__(self):
            self.calls = 0

        async def readline(self):
            self.calls += 1
            if self.calls == 1:
                state["init_read"] = True
                return b'{"id":"mail-agent-init","result":{"userAgent":"codex"}}\n'
            if self.calls == 2:
                return b'{"id":"mail-agent-rate","result":{"rateLimits":{"primary":{"usedPercent":25}}}}\n'
            if self.calls == 3:
                return b'{"id":"mail-agent-usage","result":{"summary":{"lifetimeTokens":123}}}\n'
            return b""

    class FakeProc:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.stderr = None
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    class FakeProvider:
        def _command(self, *_args):
            return ["codex", "app-server"]

    async def fake_create(*_args, **_kwargs):
        return FakeProc()

    monkeypatch.setattr(usage_module.asyncio, "create_subprocess_exec", fake_create)
    rate, usage, error = asyncio.run(CodexUsageReader(FakeProvider())._rpc())

    assert error is None
    assert rate["rateLimits"]["primary"]["usedPercent"] == 25
    assert usage["summary"]["lifetimeTokens"] == 123
    assert [item["method"] for item in state["writes"]] == [
        "initialize",
        "initialized",
        "account/rateLimits/read",
        "account/usage/read",
    ]
