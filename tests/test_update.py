from __future__ import annotations

from mail_agent_core.update import UpdateClient, UpdateInfo


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def test_update_client_detects_new_preview(monkeypatch):
    payload = {
        "name": "MAIL-AGENT Preview v0.2.6",
        "html_url": "https://example.test/release",
        "assets": [
            {
                "name": "Mail-Agent-Setup.exe",
                "browser_download_url": "https://example.test/Mail-Agent-Setup.exe",
            }
        ],
    }
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse(payload))
    info = UpdateClient(feed_url="https://example.test/api").check("0.2.5")
    assert info.available is True
    assert info.latest_version == "0.2.6"
    assert info.installer_url.endswith("Mail-Agent-Setup.exe")


def test_update_client_reports_current_version(monkeypatch):
    payload = {
        "name": "MAIL-AGENT Preview v0.2.5",
        "assets": [
            {
                "name": "Mail-Agent-Setup.exe",
                "browser_download_url": "https://example.test/Mail-Agent-Setup.exe",
            }
        ],
    }
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse(payload))
    info = UpdateClient(feed_url="https://example.test/api").check("0.2.5")
    assert info.available is False
    assert info.latest_version == "0.2.5"


def test_update_info_public_does_not_hide_feed_errors():
    info = UpdateInfo(
        current_version="0.2.5",
        latest_version=None,
        available=False,
        installer_url=None,
        release_page="https://example.test",
        error="private feed",
    )
    assert info.public()["error"] == "private feed"
