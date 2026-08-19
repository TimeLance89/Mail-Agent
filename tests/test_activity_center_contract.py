from pathlib import Path


def test_activity_center_gateway_and_ui_are_wired():
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    ui = Path("apps/web/app.js").read_text(encoding="utf-8")
    assert '@app.get("/v1/agent/activity")' in gateway
    assert 'agent_runtime.activity.recent_traces(25)' in gateway
    assert "activity:'Agent Activity'" in ui
    assert 'renderActivityCenter()' in ui
    assert 'Was der Agent tut – und warum.' in ui


def test_activity_center_version_is_synchronized():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    launcher = Path("apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    assert 'version = "0.9.0"' in pyproject
    assert 'APP_VERSION = "0.9.0"' in gateway
    assert 'APP_VERSION = "0.9.0"' in launcher
    assert '#define MyAppVersion "0.9.0"' in installer
