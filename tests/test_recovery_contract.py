from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reliability_routes_and_startup_recovery_are_wired():
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    assert re.search(r'^APP_VERSION = "[^"]+"$', main, re.MULTILINE)
    assert "RecoveryManager(" in main
    assert "recovery_manager.recover_stale_executions()" in main
    assert '@app.get("/v1/system/health")' in main
    assert '@app.post("/v1/system/recovery/approvals/{approval_id}/reconcile")' in main
    assert 'execution_status") in {"failed", "uncertain", "ready"}' in main


def test_startup_recovery_immediately_claims_orphaned_executions():
    recovery = (ROOT / "apps/gateway/mail_agent_gateway/recovery.py").read_text(encoding="utf-8")
    assert "max_age_seconds: int = 0" in recovery
    assert "max(0, max_age_seconds)" in recovery
    assert "execution_status='uncertain'" in recovery
    assert "execution_status='failed'" in recovery
    assert "execution_status='ready'" in recovery
    assert "already_sent" in recovery


def test_system_health_ui_and_uncertain_send_reconciliation_are_visible():
    app = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")
    assert "systemHealth" in app
    assert "renderSystemHealth()" in app
    assert "Systemzustand" in app
    assert "RELIABILITY & RECOVERY" in app
    assert "data-reconcile-sent" in app
    assert "data-reconcile-retry" in app
    assert "ein automatischer Retry könnte die Mail doppelt senden" in app
    assert "/v1/system/health" in app
    assert "/v1/system/recovery/approvals/" in app


def test_calendar_gateway_loads_only_after_frozen_environment_is_authoritative():
    entry = (ROOT / "apps/launcher/mail_agent_launcher/v17_entry.py").read_text(encoding="utf-8")
    configure = "launcher.configure_environment(data_dir)"
    calendar_import = "from mail_agent_gateway import main_v17 as _gateway_v17"
    assert configure in entry
    assert calendar_import in entry
    assert entry.index(configure) < entry.index(calendar_import)
    assert "MAIL_AGENT_WEB_DIR" in (
        ROOT / "apps/launcher/mail_agent_launcher/v16_entry.py"
    ).read_text(encoding="utf-8")


def test_release_version_is_synchronized_for_0170():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    gateway_base = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    gateway_v16 = (ROOT / "apps/gateway/mail_agent_gateway/main_v16.py").read_text(encoding="utf-8")
    gateway_v17 = (ROOT / "apps/gateway/mail_agent_gateway/main_v17.py").read_text(encoding="utf-8")
    launcher_base = (ROOT / "apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    launcher_v16 = (ROOT / "apps/launcher/mail_agent_launcher/v16_entry.py").read_text(encoding="utf-8")
    launcher_v17 = (ROOT / "apps/launcher/mail_agent_launcher/v17_entry.py").read_text(encoding="utf-8")
    launcher_entry = (ROOT / "apps/launcher/mail_agent_launcher_entry.py").read_text(encoding="utf-8")
    identity = (ROOT / "packages/agent_core/mail_agent_core/identity.py").read_text(encoding="utf-8")
    installer = (ROOT / "packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    desktop = (ROOT / "apps/web/desktop-links.js").read_text(encoding="utf-8")
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/build-installers.yml").read_text(encoding="utf-8")

    assert 'version = "0.17.0"' in pyproject
    assert 'mail-agent = "mail_agent_launcher.v17_entry:main"' in pyproject
    assert 'APP_VERSION = "0.17.0"' in gateway_v17
    assert 'APP_VERSION = "0.17.0"' in launcher_v17
    assert "from mail_agent_launcher.v17_entry import main" in launcher_entry
    assert 'app_version: str = "0.17.0"' in identity
    assert '#define MyAppVersion "0.17.0"' in installer
    assert "const APP_VERSION = '0.17.0'" in desktop
    assert "/assets/startup-rescue.js?v=0.17.0" in index
    assert "/assets/calendar-ui.js?v=0.17.0" in index
    assert "/assets/desktop-links.js?v=0.17.0" in index
    assert 'APP_VERSION = "0.16.1"' in gateway_v16
    assert 'APP_VERSION = "0.16.1"' in launcher_v16
    assert re.search(r'^APP_VERSION = "[^"]+"$', gateway_base, re.MULTILINE)
    assert re.search(r'^APP_VERSION = "[^"]+"$', launcher_base, re.MULTILINE)
    assert '"apps/gateway/mail_agent_gateway/main.py"' in workflow
    assert '"apps/launcher/mail_agent_launcher/main.py"' in workflow
    assert "Could not synchronize APP_VERSION" in workflow
