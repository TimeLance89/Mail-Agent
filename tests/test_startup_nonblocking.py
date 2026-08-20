from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STARTUP_GUARD = ROOT / "apps/web/startup-rescue.js"
DASHBOARD_LIVE = ROOT / "apps/web/dashboard-live.js"
DESKTOP_LINKS = ROOT / "apps/web/desktop-links.js"


def test_static_startup_shell_is_present_before_javascript_boot():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert 'id="startup-shell"' in index
    assert 'id="startup-detail"' in index
    assert "Oberfläche wird initialisiert" in index


def test_startup_guard_runs_immediately_after_main_app():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/startup-rescue.js?v=0.13.9" in index
    assert index.index("/assets/app.js?v=0.13.9") < index.index(
        "/assets/startup-rescue.js?v=0.13.9"
    )
    assert index.index("/assets/startup-rescue.js?v=0.13.9") < index.index(
        "/assets/mail-provider-setup.js?v=0.13.9"
    )
    assert index.index("/assets/mail-provider-setup.js?v=0.13.9") < index.index(
        "/assets/llm-model-settings-v2.js?v=0.13.9"
    )


def test_every_web_asset_is_cache_busted_for_the_hotfix():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    for asset in (
        "styles.css",
        "agent-settings.css",
        "attention-center.css",
        "mail-provider-setup.css",
        "app.js",
        "startup-rescue.js",
        "mail-provider-setup.js",
        "llm-model-settings-v2.js",
        "dashboard-live.js",
        "attention-center.js",
        "desktop-links.js",
    ):
        assert f"/assets/{asset}?v=0.13.9" in index


def test_installed_dashboard_can_render_before_optional_provider_enrichment_finishes():
    source = STARTUP_GUARD.read_text(encoding="utf-8")
    assert "installed === true" in source
    assert "typeof render === 'function'" in source
    assert "render();" in source
    assert "if (silent) return Promise.resolve();" in source
    assert "loadRuntimeSettings = backgroundLoader" in source
    assert "loadSystemHealth = backgroundLoader" in source
    assert "Promise.race" in source
    assert "BACKGROUND_WAIT_MS" in source


def test_bootstrap_status_has_independent_hard_timeout_and_visible_failure_state():
    source = STARTUP_GUARD.read_text(encoding="utf-8")
    assert "BOOTSTRAP_TIMEOUT_MS = 5000" in source
    assert "new AbortController()" in source
    assert "cache: 'no-store'" in source
    assert "fetchJsonWithTimeout('/v1/onboarding/status')" in source
    assert "hydrateBootstrapStatus(status)" in source
    assert "showBootstrapFailure(error)" in source
    assert "startup-retry" in source
    assert "startup-open-status" in source
    assert "Du musst nicht weiter warten" in source


def test_oauth_provider_status_is_optional_bootstrap_enrichment():
    source = STARTUP_GUARD.read_text(encoding="utf-8")
    assert "fetchJsonWithTimeout('/v1/oauth/providers', 2500)" in source
    assert ".catch(() => undefined)" in source


def test_ui_observers_cannot_recurse_on_their_own_dom_updates():
    dashboard = DASHBOARD_LIVE.read_text(encoding="utf-8")
    desktop = DESKTOP_LINKS.read_text(encoding="utf-8")
    provider = (ROOT / "apps/web/mail-provider-setup.js").read_text(encoding="utf-8")

    assert "observer.observe(appRoot, { childList: true });" in dashboard
    assert "observer.observe(app, { childList: true });" in desktop
    assert "observe(app, {childList:true})" in provider
    assert "subtree: true" not in dashboard
    assert "subtree: true" not in desktop
    assert "subtree: true" not in provider
    assert "if (kicker.textContent !== text) kicker.textContent = text;" in dashboard
    assert "if (footer && footer.textContent !== text) footer.textContent = text;" in desktop


def test_startup_guard_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    for source in (STARTUP_GUARD, DASHBOARD_LIVE, DESKTOP_LINKS, ROOT / "apps/web/mail-provider-setup.js"):
        result = subprocess.run(
            [node, "--check", str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
