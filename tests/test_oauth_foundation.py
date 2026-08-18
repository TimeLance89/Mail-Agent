from pathlib import Path

from mail_agent_google import GoogleOAuthClient
from mail_agent_google.client import make_pkce_pair as google_pkce
from mail_agent_microsoft import MicrosoftOAuthClient
from mail_agent_microsoft.client import make_pkce_pair as microsoft_pkce
from mail_agent_gateway.key_store import FileMasterKeyStore


def test_google_pkce_and_authorization_url():
    verifier, challenge = google_pkce()
    assert len(verifier) >= 43
    assert challenge
    url = GoogleOAuthClient("client-id").authorization_url(
        redirect_uri="http://127.0.0.1:8765",
        state="state-value",
        code_challenge=challenge,
    )
    assert "code_challenge_method=S256" in url
    assert "gmail.modify" in url


def test_microsoft_pkce_and_authorization_url():
    verifier, challenge = microsoft_pkce()
    assert len(verifier) >= 43
    url = MicrosoftOAuthClient("client-id").authorization_url(
        redirect_uri="http://localhost:8765/v1/oauth/microsoft/callback",
        state="state-value",
        code_challenge=challenge,
    )
    assert "code_challenge_method=S256" in url
    assert "Mail.Read" in url


def test_file_key_store_is_stable(tmp_path: Path):
    store = FileMasterKeyStore(tmp_path / "vault.key")
    first = store.get_or_create()
    second = store.get_or_create()
    assert len(first) == 32
    assert first == second
