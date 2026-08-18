from __future__ import annotations

import asyncio

import mail_agent_gateway.main as gateway


class FakeUpdateInfo:
    def public(self):
        return {
            "current_version": gateway.APP_VERSION,
            "latest_version": "0.3.1",
            "available": True,
            "installer_url": "https://example.test/Mail-Agent-Setup.exe",
            "expected_sha256": "a" * 64,
            "installer_size": 150_000,
            "release_page": "https://example.test/release",
            "error": None,
        }


def test_update_status_exposes_web_ui_metadata(monkeypatch):
    monkeypatch.setattr(gateway.update_client, "check", lambda _version: FakeUpdateInfo())
    result = asyncio.run(gateway.system_update_status())
    assert result["current_version"] == "0.3.0"
    assert result["available"] is True
    assert result["channel"] == "Preview"
    assert result["automatic_checks"] is True
    assert result["check_interval_seconds"] == 21600
