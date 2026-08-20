from __future__ import annotations

from mail_agent_gateway.adaptive_intelligence import CodexUsageReader


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
