from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STARTUP_GUARD = ROOT / "apps/web/startup-rescue.js"


def test_static_startup_shell_is_present_before_javascript_boot():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert 'id="startup-shell"' in index
    assert 'id="startup-detail"' in index
    assert "Oberfläche wird initialisiert" in index


def test_startup_guard_runs_immediately_after_main_app():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/startup-rescue.js" in index
    assert index.index("/assets/app.js") < index.index("/assets/startup-rescue.js")
    assert index.index("/assets/startup-rescue.js") < index.index("/assets/llm-model-settings-v2.js")


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


def test_startup_guard_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run(
        [node, "--check", str(STARTUP_GUARD)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
