from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import pytest

from mail_agent_core.providers import CodexCliProvider, CompletionRequest


@pytest.mark.asyncio
async def test_codex_sends_large_prompt_via_stdin_not_argv(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"ok":true}', b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    huge_mail = "X" * 200_000
    await CodexCliProvider("codex").complete(
        CompletionRequest(
            system="system",
            user=huge_mail,
            model="chosen-model-id",
            json_schema={"type": "object"},
        )
    )

    command = list(create.call_args.args)
    assert command == [
        "/fake/codex",
        "exec",
        "--skip-git-repo-check",
        "-m",
        "chosen-model-id",
        "-",
    ]
    assert create.call_args.kwargs["stdin"] is not None

    sent = proc.communicate.await_args.kwargs["input"]
    assert isinstance(sent, bytes)
    payload = json.loads(sent.decode("utf-8"))
    assert payload["task"] == huge_mail
    assert huge_mail not in " ".join(command)


@pytest.mark.asyncio
async def test_codex_default_model_uses_stdin_sentinel_without_model_flag(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b"result", b""))
    create = AsyncMock(return_value=proc)
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)

    result = await CodexCliProvider("codex").complete(
        CompletionRequest(system="system", user="mail", model="default")
    )

    assert result == "result"
    assert create.call_args.args == ("/fake/codex", "exec", "--skip-git-repo-check", "-")
    proc.communicate.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_execution_timeout_terminates_process_tree(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    monkeypatch.setattr("mail_agent_core.providers._hidden_process_creationflags", lambda: 0)

    proc = Mock(returncode=None, pid=123)
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    create = AsyncMock(return_value=proc)
    terminate = AsyncMock()
    monkeypatch.setattr("mail_agent_core.providers.asyncio.create_subprocess_exec", create)
    monkeypatch.setattr("mail_agent_core.providers._terminate_process_tree", terminate)

    with pytest.raises(RuntimeError, match="Codex execution timed out"):
        await CodexCliProvider("codex").complete(
            CompletionRequest(system="system", user="mail", model="default")
        )

    terminate.assert_awaited_once_with(proc)
