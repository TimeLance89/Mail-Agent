from unittest.mock import Mock

from mail_agent_core.providers import CodexCliProvider


def test_codex_chatgpt_login_uses_official_cli(monkeypatch):
    monkeypatch.setattr("mail_agent_core.providers.shutil.which", lambda _: "/fake/codex")
    popen = Mock()
    monkeypatch.setattr("mail_agent_core.providers.subprocess.Popen", popen)
    detail = CodexCliProvider("codex").start_chatgpt_login()
    assert "ChatGPT" in detail
    assert popen.call_args.args[0] == ["/fake/codex", "--login"]
