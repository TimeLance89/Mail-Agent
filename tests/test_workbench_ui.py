from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_workbench_is_first_class_and_adaptive_assets_are_loaded():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/workbench.css?v=0.16.1" in index
    assert "/assets/workbench-ui.js?v=0.16.1" in index
    assert "/assets/adaptive-intelligence.css?v=0.16.1" in index
    assert "/assets/adaptive-intelligence-ui.js?v=0.16.1" in index
    assert "/assets/dashboard-live.js?v=0.16.1" in index
    assert "/assets/attention-center.js" not in index


def test_workbench_preserves_direct_actions_and_inherits_existing_dashboard_bindings():
    source = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")
    app = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")

    for marker in (
        "runAgentNow",
        "syncNow",
        "data-approve",
        "data-reject",
        "data-draft-edit",
        "data-draft-submit",
        "/v1/attention?limit=200",
        "/v1/attention/resolve",
        "/v1/settings/behavior",
        "mark_processed_read",
        "newsletter_action",
        "advertising_action",
        "saveBehaviorSettings",
        "check-update",
        "install-update",
        "originalBindDashboard();",
    ):
        assert marker in source

    for control_id in (
        "settings-provider-test",
        "settings-chatgpt-login",
        "settings-save-llm",
        "settings-save-profile",
        "settings-save-brain",
        "settings-refresh-brain",
        "settings-add-rule",
    ):
        assert f'id="{control_id}"' in source
        assert f"'{control_id}'" in app

    assert "saveBrainSettings" in app
    assert "probeSettingsProvider" in app


def test_adaptive_ui_has_opt_in_review_routing_usage_and_no_mutation_observer():
    source = (ROOT / "apps/web/adaptive-intelligence-ui.js").read_text(encoding="utf-8")
    for marker in (
        "/v1/owner-profile/consent",
        "/v1/owner-profile/preview",
        "/v1/owner-profile/activate",
        "/v1/settings/model-routing",
        "/v1/usage?days=7",
        "Provider gemeldet",
        "geschätzt",
        "unbekannt",
        "Automatisch · empfohlen",
        "Expertenmodus",
        "Vorschau",
    ):
        assert marker in source
    assert "new MutationObserver" not in source
    assert "setInterval" not in source


def test_workbench_has_real_filters_and_command_palette_not_preview_controls():
    source = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")
    assert "data-inbox-filter" in source
    assert "data-attention-filter" in source
    assert "function openCommand()" in source
    assert 'data-command-action="sync"' in source
    assert 'data-command-action="run"' in source
    assert "design-preview" not in source
    assert "installDemoData" not in source


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/workbench-ui.js",
        "apps/web/adaptive-intelligence-ui.js",
    ],
)
def test_workbench_javascript_syntax(path: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run(
        [node, "--check", str(ROOT / path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
