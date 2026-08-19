from pathlib import Path
import re


def _project_version() -> str:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_activity_center_gateway_and_ui_are_wired():
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    ui = Path("apps/web/app.js").read_text(encoding="utf-8")
    assert '@app.get("/v1/agent/activity")' in gateway
    assert 'agent_runtime.activity.recent_traces(25)' in gateway
    assert "activity:'Agent Activity'" in ui
    assert 'renderActivityCenter()' in ui
    assert 'Was der Agent tut – und warum.' in ui


def test_activity_center_version_is_synchronized():
    version = _project_version()
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    launcher = Path("apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    assert f'APP_VERSION = "{version}"' in gateway
    assert f'APP_VERSION = "{version}"' in launcher
    assert f'#define MyAppVersion "{version}"' in installer
