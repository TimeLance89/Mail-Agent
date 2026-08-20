from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_attention_workbench_and_routes_are_wired():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    desktop = (ROOT / "apps/launcher/mail_agent_launcher/desktop_runtime.py").read_text(encoding="utf-8")

    assert "/assets/workbench-ui.js?v=0.17.2" in index
    assert "/assets/attention-center.css?v=0.17.2" in index
    assert "/assets/attention-center.js" not in index
    assert "Wartet auf dich" in js
    assert "/v1/attention?limit=200" in js
    assert "/v1/attention/resolve" in js
    assert '@app.get("/v1/attention")' in main
    assert '@app.post("/v1/attention/resolve")' in main
    assert "shadow_reports.recent_reports" in main
    assert "attention_source" in main
    assert "Shadow-Ergebnis" in js
    assert 'view="attention"' in desktop


def test_workbench_attention_has_no_recursive_mutation_observer():
    js = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")
    assert "MutationObserver" not in js


def test_workbench_attention_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run(
        [node, "--check", str(ROOT / "apps/web/workbench-ui.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
