from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_conversation_ui_adapter_is_loaded_and_has_undo():
    html=(ROOT/"apps/web/index.html").read_text(encoding="utf-8")
    source=(ROOT/"apps/web/conversation-intelligence-ui.js").read_text(encoding="utf-8")
    assert "/assets/conversation-intelligence-ui.js?v=0.18.1" in html
    assert "/v1/actions/undo/" in source
    assert "Rückgängig" in source
    assert "cold_outreach" in source
    assert "MAIL-AGENT v${VERSION}" in source
    assert "MutationObserver" not in source


def test_conversation_ui_adapter_javascript_syntax():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result=subprocess.run([node,"--check",str(ROOT/"apps/web/conversation-intelligence-ui.js")],capture_output=True,text=True,check=False)
    assert result.returncode==0,result.stderr
