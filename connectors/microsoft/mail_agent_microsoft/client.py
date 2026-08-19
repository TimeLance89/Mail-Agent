from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = (
    "openid profile email offline_access "
    "https://graph.microsoft.com/Mail.ReadWrite "
    "https://graph.microsoft.com/Mail.Send"
)

_WELL_KNOWN_FOLDERS = {
    "archive": "archive",
    "archiv": "archive",
    "deleteditems": "deleteditems",
    "deleted items": "deleteditems",
    "gelöschte elemente": "deleteditems",
    "geloschte elemente": "deleteditems",
    "trash": "deleteditems",
    "papierkorb": "deleteditems",
    "drafts": "drafts",
    "entwürfe": "drafts",
    "entwurfe": "drafts",
    "inbox": "inbox",
    "posteingang": "inbox",
    "junkemail": "junkemail",
    "junk": "junkemail",
    "spam": "junkemail",
    "sentitems": "sentitems",
    "sent items": "sentitems",
    "gesendete elemente": "sentitems",
}


def make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@dataclass(frozen=True)
class MicrosoftTokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str = ""
    token_type: str = "Bearer"

    @classmethod
    def from_response(
        cls,
        payload: dict,
        previous_refresh_token: str | None = None,
    ) -> "MicrosoftTokenSet":
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token") or previous_refresh_token,
            expires_at=time.time() + max(30, int(payload.get("expires_in", 3600)) - 30),
            scope=payload.get("scope", ""),
            token_type=payload.get("token_type", "Bearer"),
        )


class MicrosoftOAuthClient:
    def __init__(self, client_id: str, *, tenant: str = "common", timeout: float = 20.0):
        if not client_id:
            raise ValueError("Microsoft OAuth client ID is required")
        self.client_id = client_id
        self.tenant = tenant or "common"
        self.timeout = timeout

    @property
    def authorize_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize"

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"

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
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": GRAPH_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> MicrosoftTokenSet:
        data = {
            "client_id": self.client_id,
            "scope": GRAPH_SCOPES,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.token_url, data=data)
            response.raise_for_status()
            return MicrosoftTokenSet.from_response(response.json())

    async def refresh(self, refresh_token: str) -> MicrosoftTokenSet:
        data = {
            "client_id": self.client_id,
            "scope": GRAPH_SCOPES,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.token_url, data=data)
            response.raise_for_status()
            return MicrosoftTokenSet.from_response(response.json(), refresh_token)


class MicrosoftGraphClient:
    def __init__(self, access_token: str, *, timeout: float = 25.0):
        self.access_token = access_token
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Prefer": 'outlook.body-content-type="text"',
        }

    @staticmethod
    def _message_path(message_id: str) -> str:
        return f"{GRAPH_BASE}/me/messages/{quote(message_id, safe='')}"

    async def profile(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                f"{GRAPH_BASE}/me",
                params={"$select": "mail,userPrincipalName,displayName"},
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def initial_delta_url() -> str:
        query = urlencode(
            {
                "$select": (
                    "id,conversationId,internetMessageId,subject,from,toRecipients,ccRecipients,"
                    "receivedDateTime,sentDateTime,isRead,body"
                ),
            }
        )
        return f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta?{query}"

    async def delta(self, url: str | None = None) -> dict:
        target = url or self.initial_delta_url()
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                target,
                headers={
                    **self._headers,
                    "Prefer": 'odata.maxpagesize=100, outlook.body-content-type="text"',
                },
            )
            response.raise_for_status()
            return response.json()

    async def mark_read(self, message_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.patch(
                self._message_path(message_id),
                json={"isRead": True},
            )
            response.raise_for_status()
            return response.json()

    async def move_message(self, message_id: str, destination_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(
                f"{self._message_path(message_id)}/move",
                json={"destinationId": destination_id},
            )
            response.raise_for_status()
            return response.json()

    async def archive_message(self, message_id: str) -> dict:
        return await self.move_message(message_id, "archive")

    async def trash_message(self, message_id: str) -> dict:
        # Deliberately soft-delete: Microsoft Graph's well-known Deleted Items folder.
        return await self.move_message(message_id, "deleteditems")

    async def resolve_folder_id(self, display_name: str) -> str:
        normalized = (display_name or "").strip().casefold()
        if not normalized:
            raise RuntimeError("Microsoft Graph destination folder is empty")
        if normalized in _WELL_KNOWN_FOLDERS:
            return _WELL_KNOWN_FOLDERS[normalized]

        queue = [f"{GRAPH_BASE}/me/mailFolders"]
        visited: set[str] = set()
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            while queue:
                target = queue.pop(0)
                while target:
                    response = await client.get(
                        target,
                        params=(
                            {
                                "$select": "id,displayName,childFolderCount",
                                "includeHiddenFolders": "true",
                                "$top": "100",
                            }
                            if "?" not in target
                            else None
                        ),
                    )
                    response.raise_for_status()
                    payload = response.json()
                    for folder in payload.get("value", []) or []:
                        folder_id = str(folder.get("id") or "")
                        if not folder_id or folder_id in visited:
                            continue
                        visited.add(folder_id)
                        if str(folder.get("displayName") or "").strip().casefold() == normalized:
                            return folder_id
                        if int(folder.get("childFolderCount") or 0) > 0:
                            queue.append(
                                f"{GRAPH_BASE}/me/mailFolders/{quote(folder_id, safe='')}/childFolders"
                            )
                    target = payload.get("@odata.nextLink")
        raise RuntimeError(f"Microsoft Graph folder not found: {display_name}")

    async def create_reply_draft(self, source_message_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(
                f"{self._message_path(source_message_id)}/createReply",
                content=b"",
            )
            response.raise_for_status()
            return response.json()

    async def create_forward_draft(self, source_message_id: str, recipient: str) -> dict:
        payload = {
            "toRecipients": [{"emailAddress": {"address": recipient}}],
            "comment": "",
        }
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(
                f"{self._message_path(source_message_id)}/createForward",
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def update_draft(
        self,
        draft_id: str,
        *,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict:
        payload = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.patch(self._message_path(draft_id), json=payload)
            response.raise_for_status()
            return response.json()

    async def send_draft(self, draft_id: str) -> None:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(f"{self._message_path(draft_id)}/send", content=b"")
            response.raise_for_status()

    async def send_reply(
        self,
        *,
        source_message_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict:
        draft = await self.create_reply_draft(source_message_id)
        draft_id = str(draft.get("id") or "")
        if not draft_id:
            raise RuntimeError("Microsoft Graph did not return a reply draft ID")
        await self.update_draft(
            draft_id,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        await self.send_draft(draft_id)
        return {
            "id": draft_id,
            "conversationId": draft.get("conversationId"),
        }

    async def send_forward(
        self,
        *,
        source_message_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> dict:
        draft = await self.create_forward_draft(source_message_id, recipient)
        draft_id = str(draft.get("id") or "")
        if not draft_id:
            raise RuntimeError("Microsoft Graph did not return a forward draft ID")
        await self.update_draft(
            draft_id,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        await self.send_draft(draft_id)
        return {
            "id": draft_id,
            "conversationId": draft.get("conversationId"),
        }


def stable_remote_uid(remote_id: str) -> int:
    return (
        int.from_bytes(hashlib.sha256(remote_id.encode("utf-8")).digest()[:8], "big")
        & 0x7FFF_FFFF_FFFF_FFFF
    )
