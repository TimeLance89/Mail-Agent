import os
from unittest.mock import AsyncMock, Mock

import pytest

from mail_agent_core.providers import (
    CodexCliProvider,
    CompletionRequest,
    _hidden_process_creationflags,
)


def test_codex_chatgpt_login_uses_official_cli(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0x08000000)
    popen = Mock()
    monkeypatch.setattr("mail_agent_core.providers.subprocess.Popen", popen)
    detail = CodexCliProvider("codex").start_chatgpt_login()
    assert "ChatGPT" in detail
    assert popen.call_args.args[0] == ["/fake/codex", "--login"]
    assert popen.call_args.kwargs["creationflags"] == 0x08000000


def test_codex_windows_cmd_wrapper_uses_cmd_exe(monkeypatch):
    monkeypatch.setattr(
        "mail_agent_core.providers.shutil.which",
        lambda _: r"C:\Users\user\AppData\Roaming\npm\codex.CMD",
    )
    provider = CodexCliProvider("codex")
    command = provider._command("--login", platform_name="nt")
    assert command[:4] == [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"]
    assert "codex.CMD" in command[4]
    assert "--login" in command[4]


def test_windows_internal_processes_use_create_no_window(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.subprocess.CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert _hidden_process_creationflags("nt") == 0x08000000
    assert _hidden_process_creationflags("posix") == 0


@pytest.mark.asyncio
async def test_codex_health_passes_hidden_creationflags(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0x08000000)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b"codex 1.2.3", b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    result = await CodexCliProvider("codex").health()

    assert result.available is True
    assert create.call_args.kwargs["creationflags"] == 0x08000000


@pytest.mark.asyncio
async def test_codex_completion_passes_hidden_creationflags(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0x08000000)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"ok":true}', b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    result = await CodexCliProvider("codex").complete(
        CompletionRequest(system="system", user="user", model="default")
    )

    assert result == '{"ok":true}'
    assert create.call_args.kwargs["creationflags"] == 0x08000000
