from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from mail_agent_core.providers import CodexCliProvider, CompletionRequest


ROOT = Path(__file__).resolve().parents[1]
MODEL_UI = ROOT / "apps/web/llm-model-settings-v2.js"


def test_llm_model_selector_is_loaded_after_main_app():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/llm-model-settings-v2.js" in index
    assert "/assets/llm-model-settings.js" not in index
    assert index.index("/assets/app.js") < index.index("/assets/llm-model-settings-v2.js")
    assert index.index("/assets/llm-model-settings-v2.js") < index.index("/assets/dashboard-live.js")


def test_model_selector_auto_discovers_settings_and_onboarding_models():
    source = MODEL_UI.read_text(encoding="utf-8")
    assert "settings-model" in source
    assert "model-select" in source
    assert "/v1/providers/probe" in source
    assert "enhanceSettings" in source
    assert "enhanceOnboarding" in source
    assert "Modelle neu erkennen" in source
    assert "Automatisch (Codex-Standard)" in source
    assert "Expertenoption: andere Modell-ID" in source
    assert "document.createElement('select')" in source
    assert "datalist" not in source.lower()
    assert "gpt-5" not in source.lower()


def test_model_selector_observer_cannot_watch_its_own_subtree_mutations():
    source = MODEL_UI.read_text(encoding="utf-8")
    assert "observer.observe(app, { childList: true });" in source
    assert "subtree: true" not in source
    assert "react to its own DOM changes and lock up the browser" in source


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
        [node, "--check", str(MODEL_UI)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _catalog(*models: dict) -> bytes:
    return json.dumps({"models": list(models)}).encode()


@pytest.mark.asyncio
async def test_codex_discovers_visible_models_from_official_cli(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0x08000000)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(
        return_value=(
            _catalog(
                {"slug": "model-a", "display_name": "Model A", "visibility": "list"},
                {"slug": "model-b", "display_name": "Model B", "visibility": "list"},
                {"slug": "internal-model", "visibility": "hide"},
                {"slug": "model-a", "visibility": "list"},
            ),
            b"",
        )
    )
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    models = await CodexCliProvider("codex").list_models()

    assert models == ["model-a", "model-b"]
    assert create.call_args.args == ("/fake/codex", "debug", "models")
    assert create.call_args.kwargs["creationflags"] == 0x08000000


@pytest.mark.asyncio
async def test_codex_model_discovery_falls_back_to_bundled_catalog(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    failed = Mock(returncode=1)
    failed.communicate = AsyncMock(return_value=(b"", b"refresh failed"))
    bundled = Mock(returncode=0)
    bundled.communicate = AsyncMock(
        return_value=(_catalog({"slug": "bundled-model", "visibility": "list"}), b"")
    )
    create = AsyncMock(side_effect=[failed, bundled])
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    models = await CodexCliProvider("codex").list_models()

    assert models == ["bundled-model"]
    assert create.await_args_list[0].args == ("/fake/codex", "debug", "models")
    assert create.await_args_list[1].args == ("/fake/codex", "debug", "models", "--bundled")


@pytest.mark.asyncio
async def test_codex_model_discovery_timeout_terminates_process_tree(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=None, pid=321)
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    create = AsyncMock(return_value=proc)
    terminate = AsyncMock()
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)
    monkeypatch.setattr("mail_agent_core.providers._terminate_process_tree", terminate)

    models = await CodexCliProvider("codex")._debug_model_catalog(bundled=False, timeout=0.01)

    assert models == []
    terminate.assert_awaited_once_with(proc)


def test_windows_codex_cleanup_is_process_tree_aware_and_bounded():
    source = (ROOT / "packages/agent_core/mail_agent_core/providers.py").read_text(
        encoding="utf-8"
    )
    assert '["taskkill", "/PID", str(pid), "/T", "/F"]' in source
    assert "await asyncio.wait_for(proc.wait(), timeout=2.0)" in source
    assert "await proc.communicate()" not in source.split("async def _terminate_process_tree", 1)[1].split("class LLMProvider", 1)[0]


@pytest.mark.asyncio
async def test_codex_model_discovery_returns_empty_when_cli_is_missing(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: None)
    assert await CodexCliProvider("codex").list_models() == []


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
