from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_attention_ui_and_routes_are_wired():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/attention-center.js").read_text(encoding="utf-8")
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    desktop = (ROOT / "apps/launcher/mail_agent_launcher/desktop_runtime.py").read_text(encoding="utf-8")

    assert "/assets/attention-center.js?v=0.13.9" in index
    assert "/assets/attention-center.css?v=0.13.9" in index
    assert "Handlungsbedarf" in js
    assert "/v1/attention?limit=200" in js
    assert "/v1/attention/resolve" in js
    assert '@app.get("/v1/attention")' in main
    assert '@app.post("/v1/attention/resolve")' in main
    assert "shadow_reports.recent_reports" in main
    assert "attention_source" in main
    assert "Shadow-Ergebnis" in js
    assert 'view="attention"' in desktop


def test_attention_observer_is_not_recursive():
    js = (ROOT / "apps/web/attention-center.js").read_text(encoding="utf-8")
    assert ".observe(app, {childList:true})" in js
    assert "subtree:true" not in js.replace(" ", "")


def test_attention_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run([node, "--check", str(ROOT / "apps/web/attention-center.js")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
