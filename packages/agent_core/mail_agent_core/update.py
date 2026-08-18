from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_RELEASE_API = "https://api.github.com/repos/TimeLance89/Mail-Agent/releases/tags/preview-latest"
DEFAULT_RELEASE_PAGE = "https://github.com/TimeLance89/Mail-Agent/releases/tag/preview-latest"
INSTALLER_NAME = "Mail-Agent-Setup.exe"
_VERSION_RE = re.compile(r"(?<!\d)v?(\d+\.\d+\.\d+)(?!\d)", re.IGNORECASE)
_SHA256_RE = re.compile(r"(?:sha256:)?([0-9a-fA-F]{64})", re.IGNORECASE)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(value or "")
    if not match:
        raise ValueError(f"Ungültige Versionsnummer: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def _require_https(url: str, *, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise RuntimeError(f"{label} muss eine HTTPS-Adresse sein")


def _parse_sha256(value: str) -> str:
    match = _SHA256_RE.fullmatch((value or "").strip())
    if not match:
        raise RuntimeError("Release-Asset enthält keine gültige SHA-256-Prüfsumme")
    return match.group(1).lower()


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str | None
    available: bool
    installer_url: str | None
    expected_sha256: str | None
    installer_size: int | None
    release_page: str
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "available": self.available,
            "installer_url": self.installer_url,
            "expected_sha256": self.expected_sha256,
            "installer_size": self.installer_size,
            "release_page": self.release_page,
            "error": self.error,
        }


class UpdateClient:
    def __init__(
        self,
        *,
        feed_url: str = DEFAULT_RELEASE_API,
        release_page: str = DEFAULT_RELEASE_PAGE,
        token: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.feed_url = feed_url
        self.release_page = release_page
        self.token = token or None
        self.timeout = timeout

    def _headers(self, *, api: bool = False) -> dict[str, str]:
        headers = {"User-Agent": "MAIL-AGENT"}
        if api:
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2026-03-10"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def check(self, current_version: str) -> UpdateInfo:
        try:
            _require_https(self.feed_url, label="Update-Feed")
            response = httpx.get(
                self.feed_url,
                headers=self._headers(api=True),
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            latest = self._release_version(payload)
            installer = self._asset(payload, INSTALLER_NAME)
            installer_url = installer.get("browser_download_url") if installer else None
            installer_size = int(installer.get("size") or 0) if installer else None
            digest_value = str(installer.get("digest") or "") if installer else ""
            expected_sha256 = _parse_sha256(digest_value) if digest_value else None
            is_newer = bool(latest and _version_tuple(latest) > _version_tuple(current_version))
            if is_newer and not installer_url:
                raise RuntimeError("Die neue Release-Version enthält keinen Windows-Installer")
            if is_newer and not expected_sha256:
                raise RuntimeError("Der Windows-Installer besitzt keine von GitHub veröffentlichte SHA-256-Prüfsumme")
            if installer_url:
                _require_https(installer_url, label="Update-Installer")
            return UpdateInfo(
                current_version=current_version,
                latest_version=latest,
                available=bool(is_newer and installer_url and expected_sha256),
                installer_url=installer_url,
                expected_sha256=expected_sha256,
                installer_size=installer_size or None,
                release_page=payload.get("html_url") or self.release_page,
            )
        except Exception as exc:
            return UpdateInfo(
                current_version=current_version,
                latest_version=None,
                available=False,
                installer_url=None,
                expected_sha256=None,
                installer_size=None,
                release_page=self.release_page,
                error=str(exc),
            )

    @staticmethod
    def _release_version(payload: dict[str, Any]) -> str | None:
        candidates = [payload.get("name", ""), payload.get("body", ""), payload.get("tag_name", "")]
        for candidate in candidates:
            match = _VERSION_RE.search(candidate or "")
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _asset(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
        for asset in payload.get("assets") or []:
            if asset.get("name") == name:
                return asset
        return None

    def download(self, info: UpdateInfo, destination: Path | None = None) -> Path:
        if not info.available or not info.installer_url or not info.expected_sha256:
            raise RuntimeError("Kein verifiziertes Update verfügbar")
        _require_https(info.installer_url, label="Update-Installer")
        if destination is None:
            destination = Path(tempfile.gettempdir()) / f"Mail-Agent-Setup-{info.latest_version}.exe"
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(f"{destination.name}.part")
        partial.unlink(missing_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with httpx.stream(
                "GET",
                info.installer_url,
                headers=self._headers(),
                timeout=120.0,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        digest.update(chunk)
                        size += len(chunk)
                        handle.write(chunk)
            if size < 100_000:
                raise RuntimeError("Das heruntergeladene Update ist unvollständig")
            if info.installer_size and size != info.installer_size:
                raise RuntimeError(
                    f"Update-Größe stimmt nicht überein ({size} statt {info.installer_size} Bytes)"
                )
            actual_sha256 = digest.hexdigest().lower()
            if actual_sha256 != info.expected_sha256.lower():
                raise RuntimeError("SHA-256-Prüfung des Updates fehlgeschlagen")
            os.replace(partial, destination)
            return destination
        except Exception:
            partial.unlink(missing_ok=True)
            raise
