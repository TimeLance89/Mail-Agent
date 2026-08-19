from __future__ import annotations

from pathlib import Path
import re


def _project_version() -> str:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_shadow_mode_api_contract_is_exposed():
    main = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    assert '@app.get("/v1/agent/shadow")' in main
    assert '@app.post("/v1/agent/shadow/replay")' in main
    assert '@app.get("/v1/agent/shadow/jobs/{job_id}")' in main
    assert '@app.post("/v1/agent/rules/simulate")' in main
    assert '"shadow_side_effects_forbidden": True' in main


def test_shadow_mode_ui_explains_zero_side_effects():
    web = Path("apps/web/app.js").read_text(encoding="utf-8")
    assert "Testmodus" in web
    assert "Shadow Mode" in web
    assert "Historical Replay" in web or "HISTORICAL REPLAY" in web
    assert "Rule Simulator" in web or "RULE SIMULATOR" in web
    assert "0 Side Effects" in web or "0 SIDE EFFECTS" in web


def test_shadow_mode_version_matches_current_release():
    version = _project_version()
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    launcher = Path("apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    identity = Path("packages/agent_core/mail_agent_core/identity.py").read_text(encoding="utf-8")
    assert f'APP_VERSION = "{version}"' in gateway
    assert f'APP_VERSION = "{version}"' in launcher
    assert f'#define MyAppVersion "{version}"' in installer
    assert f'app_version: str = "{version}"' in identity
