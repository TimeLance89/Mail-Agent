from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

ALLOWED_DESKTOP_VIEWS = {
    "overview",
    "activity",
    "shadow",
    "system",
    "inbox",
    "approvals",
    "drafts",
    "settings",
}


@dataclass(frozen=True)
class DesktopStatus:
    key: str
    label: str
    paused: bool
    execution_mode: str
    approval_count: int
    draft_count: int
    pending_count: int
    health_overall: str


@dataclass(frozen=True)
class DesktopNotification:
    title: str
    message: str
    view: str


@dataclass
class NotificationTracker:
    """Deduplicate owner notifications using opaque local IDs only."""

    initialized: bool = False
    approval_ids: set[str] = field(default_factory=set)
    draft_ids: set[str] = field(default_factory=set)
    health_error_ids: set[str] = field(default_factory=set)

    def observe(
        self,
        *,
        approvals: list[dict[str, Any]],
        drafts: list[dict[str, Any]],
        health: dict[str, Any],
    ) -> list[DesktopNotification]:
        approval_ids = {
            str(item.get("approval_id")) for item in approvals if item.get("approval_id")
        }
        draft_ids = {
            str(item.get("draft_id"))
            for item in drafts
            if item.get("draft_id")
            and item.get("status") != "sent"
            and not item.get("approval_id")
        }
        health_error_ids = {
            str(item.get("id"))
            for item in health.get("checks", [])
            if item.get("status") == "error" and item.get("id")
        }

        if not self.initialized:
            self.initialized = True
            self.approval_ids = approval_ids
            self.draft_ids = draft_ids
            self.health_error_ids = health_error_ids
            return []

        notifications: list[DesktopNotification] = []
        new_approvals = approval_ids - self.approval_ids
        new_drafts = draft_ids - self.draft_ids
        new_health_errors = health_error_ids - self.health_error_ids

        if new_approvals:
            count = len(new_approvals)
            notifications.append(
                DesktopNotification(
                    title="Freigabe erforderlich",
                    message=(
                        "Eine neue Aktion wartet auf deine Entscheidung."
                        if count == 1
                        else f"{count} neue Aktionen warten auf deine Entscheidung."
                    ),
                    view="approvals",
                )
            )
        if new_drafts:
            count = len(new_drafts)
            notifications.append(
                DesktopNotification(
                    title="Entwurf bereit",
                    message=(
                        "Ein neuer Entwurf wurde vorbereitet."
                        if count == 1
                        else f"{count} neue Entwürfe wurden vorbereitet."
                    ),
                    view="drafts",
                )
            )
        if new_health_errors:
            notifications.append(
                DesktopNotification(
                    title="MAIL-AGENT braucht Aufmerksamkeit",
                    message="Ein Systemproblem sollte geprüft werden.",
                    view="system",
                )
            )

        self.approval_ids = approval_ids
        self.draft_ids = draft_ids
        self.health_error_ids = health_error_ids
        return notifications


def desktop_view_url(base_url: str, view: str = "overview") -> str:
    selected = view if view in ALLOWED_DESKTOP_VIEWS else "overview"
    return f"{base_url.rstrip('/')}/?{urlencode({'view': selected})}"


def summarize_desktop_status(
    *,
    settings: dict[str, Any],
    brain: dict[str, Any],
    approvals: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    health: dict[str, Any],
) -> DesktopStatus:
    behavior = settings.get("behavior") or {}
    paused = not bool(behavior.get("enabled", True))
    execution_mode = str(behavior.get("execution_mode") or "live")
    pending_count = int(brain.get("pending_total") or 0)
    approval_count = len(approvals)
    draft_count = sum(
        1
        for item in drafts
        if item.get("status") != "sent" and not item.get("approval_id")
    )
    health_overall = str(health.get("overall") or "unknown")

    if health_overall == "action_required":
        key, label = "error", "Aktion erforderlich"
    elif paused:
        key, label = "paused", "Pausiert"
    elif execution_mode == "shadow":
        key, label = "shadow", "Shadow Mode"
    elif approval_count or draft_count or pending_count:
        key, label = "work", "Arbeit vorhanden"
    else:
        key, label = "active", "Aktiv"

    return DesktopStatus(
        key=key,
        label=label,
        paused=paused,
        execution_mode=execution_mode,
        approval_count=approval_count,
        draft_count=draft_count,
        pending_count=pending_count,
        health_overall=health_overall,
    )


class DesktopGatewayClient:
    """Loopback-only client for the desktop shell."""

    def __init__(self, base_url: str, *, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("MAIL-AGENT Gateway returned an invalid response")
        return data

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        settings = self.request("/v1/settings")
        behavior = dict(settings.get("behavior") or {})
        behavior["enabled"] = enabled
        return self.request(
            "/v1/settings/behavior",
            method="PUT",
            payload={"behavior": behavior},
        )

    def snapshot(self) -> dict[str, Any]:
        settings = self.request("/v1/settings")
        brain = self.request("/v1/agent/brain")
        approvals = self.request("/v1/approvals?status=attention&limit=100").get(
            "approvals", []
        )
        drafts = self.request("/v1/drafts?limit=100").get("drafts", [])
        health = self.request("/v1/system/health")
        status = summarize_desktop_status(
            settings=settings,
            brain=brain,
            approvals=approvals,
            drafts=drafts,
            health=health,
        )
        return {
            "settings": settings,
            "brain": brain,
            "approvals": approvals,
            "drafts": drafts,
            "health": health,
            "status": status,
        }
