from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from urllib.parse import urlencode

import httpx

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _token_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        detail = response.text.strip()[:500]
        return f"Google OAuth token endpoint returned HTTP {response.status_code}: {detail or 'no response body'}"

    error = str(payload.get("error") or f"http_{response.status_code}")
    description = str(payload.get("error_description") or "").strip()
    error_uri = str(payload.get("error_uri") or "").strip()
    parts = [f"Google OAuth token error: {error}"]
    if description:
        parts.append(description)
    if error_uri:
        parts.append(error_uri)
    return " — ".join(parts)


@dataclass(frozen=True)
class GoogleTokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str = ""
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, payload: dict, previous_refresh_token: str | None = None) -> "GoogleTokenSet":
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or previous_refresh_token,
            expires_at=time.time() + max(30, int(payload.get("expires_in", 3600)) - 30),
            scope=payload.get("scope", ""),
            token_type=payload.get("token_type", "Bearer"),
        )


class GoogleOAuthClient:
    def __init__(self, client_id: str, client_secret: str | None = None, *, timeout: float = 20.0):
        if not client_id:
            raise ValueError("Google OAuth client ID is required")
        self.client_id = client_id
        self.client_secret = client_secret or None
        self.timeout = timeout

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        login_hint: str | None = None,
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, *, code: str, redirect_uri: str, code_verifier: str) -> GoogleTokenSet:
        data = {
            "client_id": self.client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=data)
            if response.is_error:
                raise RuntimeError(_token_error_message(response))
            return GoogleTokenSet.from_response(response.json())

    async def refresh(self, refresh_token: str) -> GoogleTokenSet:
        data = {
            "client_id": self.client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(GOOGLE_TOKEN_URL, data=data)
            if response.is_error:
                raise RuntimeError(_token_error_message(response))
            return GoogleTokenSet.from_response(response.json(), refresh_token)


class GoogleGmailClient:
    def __init__(self, access_token: str, *, timeout: float = 25.0):
        self.access_token = access_token
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def profile(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(f"{GMAIL_API}/users/me/profile")
            response.raise_for_status()
            return response.json()

    async def list_message_ids(self, *, max_results: int = 100, label_id: str = "INBOX") -> list[str]:
        max_results = max(1, min(max_results, 500))
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                f"{GMAIL_API}/users/me/messages",
                params={"maxResults": max_results, "labelIds": label_id},
            )
            response.raise_for_status()
            return [item["id"] for item in response.json().get("messages", [])]

    async def get_raw_message(self, message_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                f"{GMAIL_API}/users/me/messages/{message_id}",
                params={"format": "raw"},
            )
            response.raise_for_status()
            payload = response.json()
        raw = payload.get("raw", "")
        padding = "=" * (-len(raw) % 4)
        payload["raw_bytes"] = base64.urlsafe_b64decode(raw + padding)
        return payload

    async def history(self, *, start_history_id: str, page_token: str | None = None) -> dict:
        params: dict[str, str | int] = {
            "startHistoryId": start_history_id,
            "labelId": "INBOX",
            "maxResults": 500,
        }
        if page_token:
            params["pageToken"] = page_token
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(f"{GMAIL_API}/users/me/history", params=params)
            response.raise_for_status()
            return response.json()


def stable_remote_uid(remote_id: str) -> int:
    return int.from_bytes(hashlib.sha256(remote_id.encode("utf-8")).digest()[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def parse_raw_headers(raw: bytes) -> dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {"subject": str(message.get("Subject", "")), "message_id": str(message.get("Message-ID", ""))}
