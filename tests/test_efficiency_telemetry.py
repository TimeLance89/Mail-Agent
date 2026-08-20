from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mail_agent_gateway.efficiency_store import EfficiencySignalStore

ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_skip_counts_tokens_as_savings_not_consumption(tmp_path: Path):
    store = EfficiencySignalStore(tmp_path / "usage.db")
    store.record_usage(
        task_class="classification",
        route="deterministic",
        provider=None,
        model=None,
        llm_calls=0,
        prompt_tokens=800,
        completion_tokens=0,
        token_source="estimated",
        duration_ms=0,
        avoided_codex=True,
        decision_origin="deterministic",
    )
    store.record_usage(
        task_class="normal_analysis",
        route="normal",
        provider="codex",
        model="luna",
        llm_calls=1,
        prompt_tokens=120,
        completion_tokens=30,
        token_source="estimated",
        duration_ms=20,
        avoided_codex=False,
        decision_origin="llm",
    )

    summary = store.summary(days=1)
    assert summary["prompt_tokens"] == 120
    assert summary["completion_tokens"] == 30
    assert summary["estimated_tokens_avoided"] == 800
    assert summary["codex_calls_avoided"] == 1


def test_efficiency_schema_remains_mail_content_free(tmp_path: Path):
    store = EfficiencySignalStore(tmp_path / "usage.db")
    columns = set(store.assert_privacy_contract()["usage_events"])
    forbidden = {"body", "subject", "sender", "recipient", "prompt", "content", "message_id"}
    assert forbidden.isdisjoint(columns)
    assert "estimated_tokens_avoided" in columns


def test_efficiency_savings_metric_is_loaded_and_has_no_dom_observer():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    source = (ROOT / "apps/web/efficiency-metrics-ui.js").read_text(encoding="utf-8")

    assert "/assets/efficiency-metrics-ui.js?v=0.17.2" in index
    assert "estimated_tokens_avoided" in source
    assert "Tokens vermieden" in source
    assert "new MutationObserver" not in source


def test_efficiency_metrics_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run(
        [node, "--check", str(ROOT / "apps/web/efficiency-metrics-ui.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
