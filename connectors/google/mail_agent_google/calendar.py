from __future__ import annotations

from urllib.parse import quote, urlencode

import httpx

from .client import GOOGLE_AUTHORIZE_URL, GoogleOAuthClient

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
CALENDAR_FREEBUSY_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"
GOOGLE_CALENDAR_SCOPES = (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_LIST_SCOPE,
    CALENDAR_FREEBUSY_SCOPE,
)


class GoogleCalendarOAuthClient(GoogleOAuthClient):
    """Desktop PKCE flow that upgrades an existing Gmail grant with Calendar access."""

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        login_hint: str | None = None,
        extra_scopes: tuple[str, ...] = GOOGLE_CALENDAR_SCOPES,
    ) -> str:
        from .client import GMAIL_SCOPE

        scopes = (GMAIL_SCOPE, *extra_scopes)
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(dict.fromkeys(scopes)),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


class GoogleCalendarClient:
    def __init__(self, access_token: str, *, timeout: float = 25.0):
        if not access_token:
            raise ValueError("Google Calendar access token is required")
        self.access_token = access_token
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _calendar_path(calendar_id: str) -> str:
        return quote(str(calendar_id or "primary"), safe="")

    async def list_calendars(self, *, max_results: int = 100) -> list[dict]:
        max_results = max(1, min(int(max_results), 250))
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                f"{CALENDAR_API}/users/me/calendarList",
                params={"maxResults": max_results, "showHidden": "false"},
            )
            response.raise_for_status()
            return list(response.json().get("items", []))

    async def list_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: str,
        time_max: str,
        max_results: int = 50,
    ) -> list[dict]:
        max_results = max(1, min(int(max_results), 250))
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.get(
                f"{CALENDAR_API}/calendars/{self._calendar_path(calendar_id)}/events",
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "maxResults": max_results,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "showDeleted": "false",
                },
            )
            response.raise_for_status()
            return list(response.json().get("items", []))

    async def freebusy(
        self,
        *,
        time_min: str,
        time_max: str,
        calendar_ids: list[str],
        time_zone: str | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": item} for item in calendar_ids],
        }
        if time_zone:
            payload["timeZone"] = time_zone
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(f"{CALENDAR_API}/freeBusy", json=payload)
            response.raise_for_status()
            return response.json()

    async def create_event(
        self,
        *,
        calendar_id: str,
        event: dict,
        send_updates: str = "none",
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.post(
                f"{CALENDAR_API}/calendars/{self._calendar_path(calendar_id)}/events",
                params={"sendUpdates": send_updates},
                json=event,
            )
            response.raise_for_status()
            return response.json()

    async def update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        patch: dict,
        send_updates: str = "none",
    ) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.patch(
                f"{CALENDAR_API}/calendars/{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}",
                params={"sendUpdates": send_updates},
                json=patch,
            )
            response.raise_for_status()
            return response.json()

    async def delete_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        send_updates: str = "none",
    ) -> None:
        async with httpx.AsyncClient(timeout=self.timeout, headers=self._headers) as client:
            response = await client.delete(
                f"{CALENDAR_API}/calendars/{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}",
                params={"sendUpdates": send_updates},
            )
            response.raise_for_status()
