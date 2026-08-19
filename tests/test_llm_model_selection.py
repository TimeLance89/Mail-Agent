from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from mail_agent_core.providers import CodexCliProvider, CompletionRequest


ROOT = Path(__file__).resolve().parents[1]


def test_llm_model_selector_is_loaded_after_main_app():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/llm-model-settings.js" in index
    assert index.index("/assets/app.js") < index.index("/assets/llm-model-settings.js")
    assert index.index("/assets/llm-model-settings.js") < index.index("/assets/dashboard-live.js")


def test_model_selector_supports_settings_onboarding_and_provider_refresh():
    source = (ROOT / "apps/web/llm-model-settings.js").read_text(encoding="utf-8")
    assert "settings-model" in source
    assert "model-select" in source
    assert "/v1/providers/probe" in source
    assert "settings-refresh-models" in source
    assert "datalist" in source
    assert "default" in source
    assert "konkrete, von deinem ChatGPT/Codex-Zugang unterstützte Modell-ID" in source


def test_existing_app_persists_selected_model():
    source = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")
    assert "document.getElementById('settings-model')" in source
    assert "put('/v1/settings/llm',{provider,model})" in source
    assert "['language','language'],['tone','tone'],['model-select','model']" in source
    assert "model:form.model||'default'" in source


def test_llm_model_selector_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run(
        [node, "--check", str(ROOT / "apps/web/llm-model-settings.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_codex_explicit_model_id_is_forwarded_with_dash_m(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"ok":true}', b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    await CodexCliProvider("codex").complete(
        CompletionRequest(system="system", user="user", model="chosen-model-id")
    )

    command = list(create.call_args.args)
    model_flag = command.index("-m")
    assert command[model_flag + 1] == "chosen-model-id"


@pytest.mark.asyncio
async def test_codex_default_model_keeps_provider_default(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"ok":true}', b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    await CodexCliProvider("codex").complete(
        CompletionRequest(system="system", user="user", model="default")
    )

    assert "-m" not in create.call_args.args
