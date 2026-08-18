import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

import mail_agent_gateway.oauth_controller as controller_module
import mail_agent_google.client as google_client_module
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.key_store import FileMasterKeyStore
from mail_agent_gateway.oauth_controller import OAuthController
from mail_agent_gateway.oauth_runtime import OAuthTokenVault
from mail_agent_gateway.settings import settings as gateway_settings
from mail_agent_gateway.state import JsonStateStore
from mail_agent_gateway.vault import CredentialVault
from mail_agent_google import GoogleOAuthClient, GoogleTokenSet
from mail_agent_google.client import GMAIL_SCOPE, _token_error_message, make_pkce_pair


class GoogleSettings:
    google_client_id = "desktop-client.apps.googleusercontent.com"
    google_client_secret = None
    google_redirect_uri = "http://127.0.0.1:8765"
    microsoft_client_id = ""
    microsoft_redirect_uri = "http://localhost:8765/v1/oauth/microsoft/callback"
    microsoft_tenant = "common"


def make_controller(tmp_path: Path) -> tuple[OAuthController, JsonStateStore, CredentialVault]:
    state = JsonStateStore(tmp_path / "state.json")
    vault = CredentialVault(
        tmp_path / "secrets.vault",
        master_key_store=FileMasterKeyStore(tmp_path / "vault.key"),
    )
    controller = OAuthController(
        settings=GoogleSettings(),
        state_store=state,
        vault=vault,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    return controller, state, vault


def test_packaged_google_desktop_credentials_are_complete():
    assert gateway_settings.google_client_id.endswith(".apps.googleusercontent.com")
    assert gateway_settings.google_client_secret


def test_google_authorization_url_is_pkce_desktop_flow():
    _, challenge = make_pkce_pair()
    url = GoogleOAuthClient("client-id").authorization_url(
        redirect_uri="http://127.0.0.1:8765",
        state="csrf-state",
        code_challenge=challenge,
    )
    query = parse_qs(urlparse(url).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8765"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [GMAIL_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["csrf-state"]
    assert query["code_challenge_method"] == ["S256"]
    assert "openid" not in query["scope"][0]


def test_google_token_exchange_sends_desktop_client_secret(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, data):
            captured.update(data)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )

    monkeypatch.setattr(google_client_module.httpx, "AsyncClient", FakeAsyncClient)
    tokens = asyncio.run(
        GoogleOAuthClient("client-id", "desktop-client-secret").exchange_code(
            code="auth-code",
            redirect_uri="http://127.0.0.1:8765",
            code_verifier="v" * 64,
        )
    )
    assert tokens.access_token == "access-token"
    assert captured["client_secret"] == "desktop-client-secret"
    assert captured["code_verifier"] == "v" * 64
    assert captured["redirect_uri"] == "http://127.0.0.1:8765"


def test_google_token_error_preserves_provider_details():
    response = httpx.Response(
        400,
        json={"error": "invalid_grant", "error_description": "Bad Request"},
    )
    message = _token_error_message(response)
    assert "invalid_grant" in message
    assert "Bad Request" in message


def test_google_callback_persists_mailbox_and_refresh_token(tmp_path: Path, monkeypatch):
    controller, state_store, vault = make_controller(tmp_path)
    session = controller.sessions.create(
        provider="google",
        code_verifier="v" * 64,
        redirect_uri=GoogleSettings.google_redirect_uri,
    )

    class FakeOAuthClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def exchange_code(self, **_kwargs):
            return GoogleTokenSet(
                access_token="access-token",
                refresh_token="refresh-token",
                expires_at=9_999_999_999,
                scope=GMAIL_SCOPE,
            )

    class FakeGmailClient:
        def __init__(self, access_token: str):
            assert access_token == "access-token"

        async def profile(self):
            return {"emailAddress": "person@gmail.com", "historyId": "123"}

    monkeypatch.setattr(controller_module, "GoogleOAuthClient", FakeOAuthClient)
    monkeypatch.setattr(controller_module, "GoogleGmailClient", FakeGmailClient)

    result = asyncio.run(controller.complete_google(state=session.state, code="auth-code"))
    assert result["status"] == "complete"
    assert result["email_address"] == "person@gmail.com"

    stored = list(state_store.read()["mailboxes"].values())[0]
    assert stored["connector"] == "gmail_api"
    assert stored["oauth_provider"] == "google"
    assert stored["credential_state"] == "encrypted-oauth-vault"
    assert stored["scope"] == GMAIL_SCOPE
    assert "access-token" not in state_store.path.read_text(encoding="utf-8")
    assert "refresh-token" not in state_store.path.read_text(encoding="utf-8")

    token_data = OAuthTokenVault(vault).load(stored["credential_ref"])
    assert token_data["refresh_token"] == "refresh-token"
    assert token_data["access_token"] == "access-token"


def test_google_callback_requires_refresh_token(tmp_path: Path, monkeypatch):
    controller, state_store, _ = make_controller(tmp_path)
    session = controller.sessions.create(
        provider="google",
        code_verifier="v" * 64,
        redirect_uri=GoogleSettings.google_redirect_uri,
    )

    class FakeOAuthClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def exchange_code(self, **_kwargs):
            return GoogleTokenSet(
                access_token="access-token",
                refresh_token=None,
                expires_at=9_999_999_999,
                scope=GMAIL_SCOPE,
            )

    monkeypatch.setattr(controller_module, "GoogleOAuthClient", FakeOAuthClient)

    try:
        asyncio.run(controller.complete_google(state=session.state, code="auth-code"))
    except RuntimeError as exc:
        assert "refresh token" in str(exc).lower()
    else:
        raise AssertionError("OAuth completion should fail without a refresh token")

    assert controller.sessions.get(session.state).status == "error"
    assert not state_store.read().get("mailboxes")
