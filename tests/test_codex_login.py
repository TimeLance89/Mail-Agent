import os
from unittest.mock import Mock

from mail_agent_core.providers import CodexCliProvider


def test_codex_chatgpt_login_uses_official_cli(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    popen = Mock()
    monkeypatch.setattr("mail_agent_core.providers.subprocess.Popen", popen)
    detail = CodexCliProvider("codex").start_chatgpt_login()
    assert "ChatGPT" in detail
    assert popen.call_args.args[0] == ["/fake/codex", "--login"]


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
