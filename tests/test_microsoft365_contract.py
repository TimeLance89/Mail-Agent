from __future__ import annotations

import asyncio
from pathlib import Path

from mail_agent_microsoft import MicrosoftGraphClient


ROOT = Path(__file__).resolve().parents[1]


def test_microsoft365_is_first_class_gateway_connector():
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "0.11.0"' in main
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
    assert "MAIL-AGENT v0.11.0" in app


def test_microsoft_well_known_folders_resolve_without_network():
    client = MicrosoftGraphClient("token")
    assert asyncio.run(client.resolve_folder_id("Archiv")) == "archive"
    assert asyncio.run(client.resolve_folder_id("Papierkorb")) == "deleteditems"


def test_011_version_is_synchronized():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    launcher = (ROOT / "apps/launcher/mail_agent_launcher/main.py").read_text(encoding="utf-8")
    identity = (ROOT / "packages/agent_core/mail_agent_core/identity.py").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "packaging/windows/MailAgent.iss").read_text(encoding="utf-8")
    assert 'version = "0.11.0"' in pyproject
    assert 'APP_VERSION = "0.11.0"' in launcher
    assert 'app_version: str = "0.11.0"' in identity
    assert '#define MyAppVersion "0.11.0"' in installer
