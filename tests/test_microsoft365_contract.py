from __future__ import annotations

import asyncio
import re
from pathlib import Path

from mail_agent_microsoft import MicrosoftGraphClient


ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_microsoft365_is_first_class_gateway_connector():
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    assert f'APP_VERSION = "{_project_version()}"' in main
    assert 'microsoft_sync_service = MicrosoftGraphSyncService(mail_store)' in main
    assert 'mailbox.get("connector") == "microsoft_graph"' in main
    assert 'current_microsoft_access_token(' in main
    assert '@app.post("/v1/oauth/microsoft/start")' in main
    assert '@app.get("/v1/oauth/microsoft/callback"' in main
    assert 'microsoft_client_id=settings.microsoft_client_id' in main
    assert 'microsoft_tenant=settings.microsoft_tenant' in main


def test_microsoft365_onboarding_is_visible_and_not_a_placeholder():
    app = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")
    assert "id=\"microsoft-connect\"" in app
    assert "connectMicrosoft" in app
    assert "/v1/oauth/microsoft/start" in app
    assert "mailboxConnector='microsoft_graph'" in app
    assert "OAuth-Anmeldung folgt als nächster Connector" not in app
    assert f"MAIL-AGENT v{_project_version()}" in app


def test_microsoft_well_known_folders_resolve_without_network():
    client = MicrosoftGraphClient("token")
    assert asyncio.run(client.resolve_folder_id("Archiv")) == "archive"
    assert asyncio.run(client.resolve_folder_id("Papierkorb")) == "deleteditems"


def test_microsoft_version_is_synchronized_with_current_release():
    version = _project_version()
    launcher = (ROOT / "apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    identity = (ROOT / "packages/agent_core/mail_agent_core/identity.py").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    assert f'APP_VERSION = "{version}"' in launcher
    assert f'app_version: str = "{version}"' in identity
    assert f'#define MyAppVersion "{version}"' in installer
