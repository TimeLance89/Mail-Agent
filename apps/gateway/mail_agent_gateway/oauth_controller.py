from __future__ import annotations

import hashlib
from dataclasses import dataclass

from mail_agent_google import (
    CALENDAR_EVENTS_SCOPE,
    GOOGLE_CALENDAR_SCOPES,
    GoogleCalendarOAuthClient,
    GoogleGmailClient,
    GoogleOAuthClient,
)
from mail_agent_google.client import GMAIL_SCOPE, make_pkce_pair as google_pkce
from mail_agent_microsoft import MicrosoftGraphClient, MicrosoftOAuthClient
from mail_agent_microsoft.client import make_pkce_pair as microsoft_pkce

from .audit import AuditLog
from .oauth_runtime import OAuthMailboxState, OAuthSessionStore, OAuthTokenVault
from .settings import Settings
from .state import JsonStateStore
from .vault import CredentialVault


@dataclass(frozen=True)
class OAuthStartResult:
    provider: str
    state: str
    authorization_url: str


def _scope_set(value: str | None) -> set[str]:
    return {item.strip() for item in str(value or "").replace(",", " ").split() if item.strip()}


def google_capabilities(scope: str | None) -> list[str]:
    scopes = _scope_set(scope)
    capabilities: list[str] = []
    if GMAIL_SCOPE in scopes:
        capabilities.append("mail")
    if CALENDAR_EVENTS_SCOPE in scopes:
        capabilities.append("calendar")
    return capabilities


class OAuthController:
    def __init__(
        self,
        *,
        settings: Settings,
        state_store: JsonStateStore,
        vault: CredentialVault,
        audit_log: AuditLog,
    ):
        self.settings = settings
        self.state_store = state_store
        self.vault = vault
        self.audit_log = audit_log
        self.sessions = OAuthSessionStore()
        self.tokens = OAuthTokenVault(vault)
        self.mailboxes = OAuthMailboxState(state_store)

    def provider_status(self) -> dict:
        return {
            "google": {
                "configured": bool(self.settings.google_client_id),
                "redirect_uri": self.settings.google_redirect_uri,
                "scope": "gmail.modify",
                "calendar_scopes": [
                    "calendar.events",
                    "calendar.calendarlist.readonly",
                    "calendar.freebusy",
                ],
                "calendar_supported": True,
            },
            "microsoft": {
                "configured": bool(self.settings.microsoft_client_id),
                "redirect_uri": self.settings.microsoft_redirect_uri,
                "tenant": self.settings.microsoft_tenant,
                "scope": "Mail.ReadWrite + Mail.Send + offline_access",
            },
        }

    def start_google(self, login_hint: str | None = None) -> OAuthStartResult:
        if not self.settings.google_client_id:
            raise RuntimeError("Google OAuth client ID is not configured")
        verifier, challenge = google_pkce()
        session = self.sessions.create(
            provider="google",
            code_verifier=verifier,
            redirect_uri=self.settings.google_redirect_uri,
            login_hint=login_hint,
            purpose="mail",
        )
        client = GoogleOAuthClient(self.settings.google_client_id, self.settings.google_client_secret)
        url = client.authorization_url(
            redirect_uri=session.redirect_uri,
            state=session.state,
            code_challenge=challenge,
            login_hint=login_hint,
        )
        self.audit_log.append(
            "oauth_started",
            details={"provider": "google", "purpose": "mail", "state": session.state},
        )
        return OAuthStartResult("google", session.state, url)

    def start_google_calendar(self, login_hint: str | None = None) -> OAuthStartResult:
        if not self.settings.google_client_id:
            raise RuntimeError("Google OAuth client ID is not configured")
        verifier, challenge = google_pkce()
        session = self.sessions.create(
            provider="google",
            code_verifier=verifier,
            redirect_uri=self.settings.google_redirect_uri,
            login_hint=login_hint,
            purpose="calendar",
        )
        client = GoogleCalendarOAuthClient(
            self.settings.google_client_id,
            self.settings.google_client_secret,
        )
        url = client.authorization_url(
            redirect_uri=session.redirect_uri,
            state=session.state,
            code_challenge=challenge,
            login_hint=login_hint,
        )
        self.audit_log.append(
            "oauth_started",
            details={"provider": "google", "purpose": "calendar", "state": session.state},
        )
        return OAuthStartResult("google", session.state, url)

    def start_microsoft(self, login_hint: str | None = None) -> OAuthStartResult:
        if not self.settings.microsoft_client_id:
            raise RuntimeError("Microsoft OAuth client ID is not configured")
        verifier, challenge = microsoft_pkce()
        session = self.sessions.create(
            provider="microsoft",
            code_verifier=verifier,
            redirect_uri=self.settings.microsoft_redirect_uri,
            login_hint=login_hint,
            purpose="mail",
        )
        client = MicrosoftOAuthClient(
            self.settings.microsoft_client_id,
            tenant=self.settings.microsoft_tenant,
        )
        url = client.authorization_url(
            redirect_uri=session.redirect_uri,
            state=session.state,
            code_challenge=challenge,
            login_hint=login_hint,
        )
        self.audit_log.append(
            "oauth_started",
            details={"provider": "microsoft", "purpose": "mail", "state": session.state},
        )
        return OAuthStartResult("microsoft", session.state, url)

    async def complete_google(self, *, state: str, code: str) -> dict:
        session = self.sessions.get(state)
        if session.provider != "google" or session.status != "pending":
            raise RuntimeError("Invalid Google OAuth session")
        try:
            client = GoogleOAuthClient(
                self.settings.google_client_id,
                self.settings.google_client_secret,
            )
            tokens = await client.exchange_code(
                code=code,
                redirect_uri=session.redirect_uri,
                code_verifier=session.code_verifier,
            )
            if not tokens.refresh_token:
                raise RuntimeError("Google did not issue a refresh token; reconnect the account")
            scopes = _scope_set(tokens.scope)
            if session.purpose == "calendar":
                missing = [scope for scope in GOOGLE_CALENDAR_SCOPES if scope not in scopes]
                if missing:
                    raise RuntimeError(
                        "Google Calendar permission was not fully granted; reconnect Calendar"
                    )
            profile = await GoogleGmailClient(tokens.access_token).profile()
            email = profile.get("emailAddress")
            if not email:
                raise RuntimeError("Google did not return a mailbox address")
            mailbox_id = _mailbox_id("google", email)
            credential_ref = self.tokens.save_google(mailbox_id, tokens)
            capabilities = google_capabilities(tokens.scope)
            self.mailboxes.upsert(
                {
                    "mailbox_id": mailbox_id,
                    "connector": "gmail_api",
                    "oauth_provider": "google",
                    "email_address": email,
                    "username": email,
                    "credential_ref": credential_ref,
                    "credential_state": "encrypted-oauth-vault",
                    "scope": tokens.scope,
                    "capabilities": capabilities,
                    "calendar_enabled": "calendar" in capabilities,
                }
            )
            self.sessions.update(
                state,
                status="complete",
                mailbox_id=mailbox_id,
                email_address=email,
            )
            self.audit_log.append(
                "oauth_connected",
                details={
                    "provider": "google",
                    "purpose": session.purpose,
                    "mailbox_id": mailbox_id,
                    "email_address": email,
                    "capabilities": capabilities,
                },
            )
            return self.sessions.get(state).public()
        except Exception as exc:
            self.sessions.update(state, status="error", error=str(exc))
            self.audit_log.append(
                "oauth_failed",
                details={"provider": "google", "purpose": session.purpose, "error": str(exc)},
            )
            raise

    async def complete_microsoft(self, *, state: str, code: str) -> dict:
        session = self.sessions.get(state)
        if session.provider != "microsoft" or session.status != "pending":
            raise RuntimeError("Invalid Microsoft OAuth session")
        try:
            client = MicrosoftOAuthClient(
                self.settings.microsoft_client_id,
                tenant=self.settings.microsoft_tenant,
            )
            tokens = await client.exchange_code(
                code=code,
                redirect_uri=session.redirect_uri,
                code_verifier=session.code_verifier,
            )
            if not tokens.refresh_token:
                raise RuntimeError("Microsoft did not issue a refresh token; reconnect the mailbox")
            profile = await MicrosoftGraphClient(tokens.access_token).profile()
            email = profile.get("mail") or profile.get("userPrincipalName")
            if not email:
                raise RuntimeError("Microsoft Graph did not return a mailbox address")
            mailbox_id = _mailbox_id("microsoft", email)
            credential_ref = self.tokens.save_microsoft(mailbox_id, tokens)
            self.mailboxes.upsert(
                {
                    "mailbox_id": mailbox_id,
                    "connector": "microsoft_graph",
                    "oauth_provider": "microsoft",
                    "email_address": email,
                    "username": profile.get("userPrincipalName") or email,
                    "display_name": profile.get("displayName") or "",
                    "credential_ref": credential_ref,
                    "credential_state": "encrypted-oauth-vault",
                    "scope": tokens.scope,
                }
            )
            self.sessions.update(
                state,
                status="complete",
                mailbox_id=mailbox_id,
                email_address=email,
            )
            self.audit_log.append(
                "oauth_connected",
                details={
                    "provider": "microsoft",
                    "mailbox_id": mailbox_id,
                    "email_address": email,
                },
            )
            return self.sessions.get(state).public()
        except Exception as exc:
            self.sessions.update(state, status="error", error=str(exc))
            self.audit_log.append(
                "oauth_failed",
                details={"provider": "microsoft", "error": str(exc)},
            )
            raise

    def fail(self, *, state: str, provider: str, error: str) -> None:
        try:
            session = self.sessions.get(state)
            self.sessions.update(state, status="error", error=error)
        except KeyError:
            return
        self.audit_log.append(
            "oauth_failed",
            details={"provider": provider, "purpose": session.purpose, "error": error},
        )


def _mailbox_id(provider: str, email_address: str) -> str:
    seed = f"{provider}|{email_address.strip().lower()}".encode("utf-8")
    return "mb_" + hashlib.sha256(seed).hexdigest()[:24]
