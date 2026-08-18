from __future__ import annotations

import hashlib
from pathlib import Path

from mail_agent_core.update import INSTALLER_NAME, UpdateClient, UpdateInfo, _parse_sha256


class FakeResponse:
    def __init__(self, payload: dict | None = None, status_code: int = 200):
        self.payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def release_payload(version: str = "0.2.9", size: int = 123456, digest: str | None = None) -> dict:
    digest = digest or ("a" * 64)
    return {
        "name": f"MAIL-AGENT Preview v{version}",
        "html_url": "https://example.test/release",
        "assets": [
            {
                "name": INSTALLER_NAME,
                "browser_download_url": f"https://example.test/{INSTALLER_NAME}",
                "size": size,
                "digest": f"sha256:{digest}",
            }
        ],
    }


def test_update_client_detects_new_preview(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse(release_payload()))
    info = UpdateClient(feed_url="https://example.test/api").check("0.2.8")
    assert info.available is True
    assert info.latest_version == "0.2.9"
    assert info.installer_url.endswith(INSTALLER_NAME)
    assert info.expected_sha256 == "a" * 64
    assert info.installer_size == 123456


def test_update_requires_github_digest(monkeypatch):
    payload = release_payload()
    payload["assets"][0]["digest"] = None
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse(payload))
    info = UpdateClient(feed_url="https://example.test/api").check("0.2.8")
    assert info.available is False
    assert info.error is not None
    assert "SHA-256" in info.error


def test_update_client_reports_current_version(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: FakeResponse(release_payload("0.2.8")))
    info = UpdateClient(feed_url="https://example.test/api").check("0.2.8")
    assert info.available is False
    assert info.latest_version == "0.2.8"


def test_parse_sha256_accepts_github_digest():
    digest = "b" * 64
    assert _parse_sha256(f"sha256:{digest}") == digest


def test_download_verifies_sha256_and_size(monkeypatch, tmp_path: Path):
    content = b"x" * 150_000
    digest = hashlib.sha256(content).hexdigest()

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield content[:75_000]
            yield content[75_000:]

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: FakeStreamResponse())
    info = UpdateInfo(
        current_version="0.2.8",
        latest_version="0.2.9",
        available=True,
        installer_url=f"https://example.test/{INSTALLER_NAME}",
        expected_sha256=digest,
        installer_size=len(content),
        release_page="https://example.test/release",
    )
    target = tmp_path / INSTALLER_NAME
    assert UpdateClient(feed_url="https://example.test/api").download(info, target) == target
    assert target.read_bytes() == content
    assert not target.with_name(target.name + ".part").exists()


def test_download_rejects_bad_digest(monkeypatch, tmp_path: Path):
    content = b"x" * 150_000

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield content

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: FakeStreamResponse())
    info = UpdateInfo(
        current_version="0.2.8",
        latest_version="0.2.9",
        available=True,
        installer_url=f"https://example.test/{INSTALLER_NAME}",
        expected_sha256="0" * 64,
        installer_size=len(content),
        release_page="https://example.test/release",
    )
    target = tmp_path / INSTALLER_NAME
    try:
        UpdateClient(feed_url="https://example.test/api").download(info, target)
    except RuntimeError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("bad digest must be rejected")
    assert not target.exists()


def test_update_info_public_keeps_errors():
    info = UpdateInfo(
        current_version="0.2.8",
        latest_version=None,
        available=False,
        installer_url=None,
        expected_sha256=None,
        installer_size=None,
        release_page="https://example.test",
        error="private feed",
    )
    assert info.public()["error"] == "private feed"
