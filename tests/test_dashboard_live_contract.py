from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_live_runtime_is_loaded_between_core_app_and_desktop_links():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    app_index = index.index('/assets/app.js')
    live_index = index.index('/assets/dashboard-live.js')
    desktop_index = index.index('/assets/desktop-links.js')
    assert app_index < live_index < desktop_index


def test_dashboard_live_runtime_centralizes_status_polling_and_friendly_errors():
    live = (ROOT / "apps/web/dashboard-live.js").read_text(encoding="utf-8")
    desktop = (ROOT / "apps/web/desktop-links.js").read_text(encoding="utf-8")

    assert "const POLL_MS = 15000" in live
    assert "function friendlyErrorMessage" in live
    assert "function liveStatus" in live
    assert "function applyLiveStatus" in live
    assert "loadDashboard(true)" in live
    assert "loadRuntimeSettings(true)" in live
    assert "loadBrainStatus(true)" in live
    assert "loadSystemHealth(true)" in live
    assert "Das lokale Gateway antwortet gerade nicht" in live
    assert "Das Postfach konnte gerade nicht vollständig synchronisiert werden" in live
    assert "Das ausgewählte KI-Modell ist momentan nicht bereit" in live
    assert "window.setInterval(refreshLiveState, POLL_MS)" in live

    assert "applyLiveStatus" not in desktop
    assert "setInterval" not in desktop


def test_dashboard_live_runtime_marks_important_mail_without_requesting_browser_notification_permission():
    live = (ROOT / "apps/web/dashboard-live.js").read_text(encoding="utf-8")
    assert "priority === 'urgent'" in live
    assert "priority === 'high'" in live
    assert "category === 'security' && item.needs_reply === true" in live
    assert "Notification.requestPermission" not in live


def test_dashboard_live_javascript_syntax_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        return
    subprocess.run(
        [node, "--check", str(ROOT / "apps/web/dashboard-live.js")],
        check=True,
        capture_output=True,
        text=True,
    )
