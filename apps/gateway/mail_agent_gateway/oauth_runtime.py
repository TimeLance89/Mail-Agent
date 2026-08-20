from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from mail_agent_google import GoogleOAuthClient, GoogleTokenSet
from mail_agent_microsoft import MicrosoftOAuthClient, MicrosoftTokenSet

from .state import JsonStateStore
from .vault import CredentialVault

OAuthProvider = Literal["google", "microsoft"]
OAuthPurpose = Literal["mail", "calendar"]


@dataclass
class OAuthSession:
    state: str
    provider: OAuthProvider
    code_verifier: str
    redirect_uri: str
    created_at: float
    login_hint: str | None = None
    purpose: OAuthPurpose = "mail"
    status: str = "pending"
    mailbox_id: str | None = None
    email_address: str | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "provider": self.provider,
            "purpose": self.purpose,
            "status": self.status,
            "mailbox_id": self.mailbox_id,
            "email_address": self.email_address,
            "error": self.error,
        }


class OAuthSessionStore:
    def __init__(self, ttl_seconds: int = 900):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, OAuthSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        provider: OAuthProvider,
        code_verifier: str,
        redirect_uri: str,
        login_hint: str | None = None,
        purpose: OAuthPurpose = "mail",
    ) -> OAuthSession:
        self.cleanup()
        session = OAuthSession(
            state=secrets.token_urlsafe(32),
            provider=provider,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            created_at=time.time(),
            login_hint=login_hint,
            purpose=purpose,
        )
        with self._lock:
            self._items[session.state] = session
        return session

    def get(self, state: str) -> OAuthSession:
        self.cleanup()
        with self._lock:
            session = self._items.get(state)
        if session is None:
            raise KeyError(state)
        return session

    def update(self, state: str, **values: Any) -> OAuthSession:
        with self._lock:
            session = self._items.get(state)
            if session is None:
                raise KeyError(state)
            for key, value in values.items():
                setattr(session, key, value)
            return session

    def cleanup(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            expired = [key for key, value in self._items.items() if value.created_at < cutoff]
            for key in expired:
                del self._items[key]


class OAuthTokenVault:
    def __init__(self, vault: CredentialVault):
        self.vault = vault

    @staticmethod
    def reference(mailbox_id: str) -> str:
        return f"mailbox:{mailbox_id}:oauth-tokens"

    def save_google(self, mailbox_id: str, tokens: GoogleTokenSet) -> str:
        return self._save(mailbox_id, "google", tokens)

    def save_microsoft(self, mailbox_id: str, tokens: MicrosoftTokenSet) -> str:
        return self._save(mailbox_id, "microsoft", tokens)

    def _save(self, mailbox_id: str, provider: str, tokens: Any) -> str:
        reference = self.reference(mailbox_id)
        self.vault.set_secret(
            reference,
            json.dumps(
                {
                    "provider": provider,
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                    "expires_at": tokens.expires_at,
                    "scope": tokens.scope,
                    "token_type": tokens.token_type,
                },
                separators=(",", ":"),
            ),
        )
        return reference

    def load(self, reference: str) -> dict[str, Any]:
        return json.loads(self.vault.get_secret(reference))


class OAuthMailboxState:
    def __init__(self, state_store: JsonStateStore):
        self.state_store = state_store

    def upsert(self, mailbox: dict[str, Any]) -> None:
        state = self.state_store.read()
        mailboxes = state.setdefault("mailboxes", {})
        if not isinstance(mailboxes, dict):
            mailboxes = {}
            state["mailboxes"] = mailboxes
        mailboxes[mailbox["mailbox_id"]] = mailbox
        state.pop("mailbox", None)
        self.state_store.write(state)


async def current_google_access_token(
    mailbox: dict[str, Any],
    *,
    vault: CredentialVault,
    client_id: str,
    client_secret: str | None,
) -> str:
    token_vault = OAuthTokenVault(vault)
    token_data = token_vault.load(mailbox["credential_ref"])
    if float(token_data.get("expires_at", 0)) > time.time() + 60:
        return token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Google refresh token is unavailable; reconnect the mailbox")
    client = GoogleOAuthClient(client_id, client_secret)
    tokens = await client.refresh(refresh_token)
    previous_scope = str(token_data.get("scope") or mailbox.get("scope") or "").strip()
    if previous_scope and not tokens.scope:
        tokens = GoogleTokenSet(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at,
            scope=previous_scope,
            token_type=tokens.token_type,
        )
    token_vault.save_google(mailbox["mailbox_id"], tokens)
    return tokens.access_token


async def current_microsoft_access_token(
    mailbox: dict[str, Any],
    *,
    vault: CredentialVault,
    client_id: str,
    tenant: str,
) -> str:
    token_vault = OAuthTokenVault(vault)
    token_data = token_vault.load(mailbox["credential_ref"])
    if float(token_data.get("expires_at", 0)) > time.time() + 60:
        return token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Microsoft refresh token is unavailable; reconnect the mailbox")
    client = MicrosoftOAuthClient(client_id, tenant=tenant)
    tokens = await client.refresh(refresh_token)
    token_vault.save_microsoft(mailbox["mailbox_id"], tokens)
    return tokens.access_token
