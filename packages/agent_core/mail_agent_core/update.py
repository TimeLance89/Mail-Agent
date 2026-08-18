from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_RELEASE_API = "https://api.github.com/repos/TimeLance89/Mail-Agent/releases/tags/preview-latest"
DEFAULT_RELEASE_PAGE = "https://github.com/TimeLance89/Mail-Agent/releases/tag/preview-latest"
INSTALLER_NAME = "Mail-Agent-Setup.exe"
_VERSION_RE = re.compile(r"(?<!\d)v?(\d+\.\d+\.\d+)(?!\d)", re.IGNORECASE)


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(value or "")
    if not match:
        raise ValueError(f"Ungültige Versionsnummer: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str | None
    available: bool
    installer_url: str | None
    release_page: str
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "available": self.available,
            "installer_url": self.installer_url,
            "release_page": self.release_page,
            "error": self.error,
        }


class UpdateClient:
    def __init__(
        self,
        *,
        feed_url: str = DEFAULT_RELEASE_API,
        release_page: str = DEFAULT_RELEASE_PAGE,
        timeout: float = 8.0,
    ) -> None:
        self.feed_url = feed_url
        self.release_page = release_page
        self.timeout = timeout

    def check(self, current_version: str) -> UpdateInfo:
        try:
            response = httpx.get(
                self.feed_url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "MAIL-AGENT"},
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            latest = self._release_version(payload)
            installer_url = self._installer_url(payload)
            available = bool(
                latest
                and installer_url
                and _version_tuple(latest) > _version_tuple(current_version)
            )
            return UpdateInfo(
                current_version=current_version,
                latest_version=latest,
                available=available,
                installer_url=installer_url,
                release_page=payload.get("html_url") or self.release_page,
            )
        except Exception as exc:
            return UpdateInfo(
                current_version=current_version,
                latest_version=None,
                available=False,
                installer_url=None,
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
    def _installer_url(payload: dict[str, Any]) -> str | None:
        for asset in payload.get("assets") or []:
            if asset.get("name") == INSTALLER_NAME:
                return asset.get("browser_download_url")
        return None

    def download(self, info: UpdateInfo, destination: Path | None = None) -> Path:
        if not info.available or not info.installer_url:
            raise RuntimeError("Kein installierbares Update verfügbar")
        if destination is None:
            destination = Path(tempfile.gettempdir()) / f"Mail-Agent-Setup-{info.latest_version}.exe"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream(
            "GET",
            info.installer_url,
            headers={"User-Agent": "MAIL-AGENT"},
            timeout=60.0,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if destination.stat().st_size < 100_000:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Das heruntergeladene Update ist unvollständig")
        return destination
