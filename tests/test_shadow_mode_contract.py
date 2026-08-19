from __future__ import annotations

from pathlib import Path


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


def test_version_is_synchronized_for_010():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    gateway = Path("apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    launcher = Path("apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    identity = Path("packages/agent_core/mail_agent_core/identity.py").read_text(encoding="utf-8")
    assert 'version = "0.10.0"' in pyproject
    assert 'APP_VERSION = "0.10.0"' in gateway
    assert 'APP_VERSION = "0.10.0"' in launcher
    assert '#define MyAppVersion "0.10.0"' in installer
    assert 'app_version: str = "0.10.0"' in identity
