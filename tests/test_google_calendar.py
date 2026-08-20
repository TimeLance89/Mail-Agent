from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import mail_agent_gateway.oauth_controller as controller_module
from mail_agent_core.models import MailActionType
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.calendar_service import (
    CalendarAction,
    CalendarApprovalStore,
    CalendarEventDraft,
    CalendarProposal,
    CalendarProposalRequest,
    CalendarService,
)
from mail_agent_gateway.key_store import FileMasterKeyStore
from mail_agent_gateway.oauth_controller import OAuthController
from mail_agent_gateway.state import JsonStateStore
from mail_agent_gateway.vault import CredentialVault
from mail_agent_google import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_FREEBUSY_SCOPE,
    CALENDAR_LIST_SCOPE,
    GoogleCalendarOAuthClient,
    GoogleTokenSet,
)
from mail_agent_google.client import GMAIL_SCOPE, make_pkce_pair


class GoogleSettings:
    google_client_id = "desktop-client.apps.googleusercontent.com"
    google_client_secret = "desktop-secret"
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


def all_google_scopes() -> str:
    return " ".join(
        [GMAIL_SCOPE, CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE, CALENDAR_FREEBUSY_SCOPE]
    )


def test_calendar_oauth_is_incremental_pkce_and_requests_narrow_scopes():
    _, challenge = make_pkce_pair()
    url = GoogleCalendarOAuthClient("client-id").authorization_url(
        redirect_uri="http://127.0.0.1:8765",
        state="state",
        code_challenge=challenge,
        login_hint="person@gmail.com",
    )
    query = parse_qs(urlparse(url).query)
    scopes = set(query["scope"][0].split())
    assert scopes == {
        GMAIL_SCOPE,
        CALENDAR_EVENTS_SCOPE,
        CALENDAR_LIST_SCOPE,
        CALENDAR_FREEBUSY_SCOPE,
    }
    assert query["include_granted_scopes"] == ["true"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["login_hint"] == ["person@gmail.com"]


def test_calendar_oauth_session_is_distinct_from_mail_oauth(tmp_path: Path):
    controller, _, _ = make_controller(tmp_path)
    result = controller.start_google_calendar("person@gmail.com")
    session = controller.sessions.get(result.state)
    assert session.provider == "google"
    assert session.purpose == "calendar"
    assert session.public()["purpose"] == "calendar"
    assert CALENDAR_EVENTS_SCOPE in parse_qs(urlparse(result.authorization_url).query)["scope"][0]


def test_calendar_oauth_upgrade_persists_capability_and_encrypted_tokens(tmp_path: Path, monkeypatch):
    controller, state_store, vault = make_controller(tmp_path)
    session = controller.sessions.create(
        provider="google",
        purpose="calendar",
        code_verifier="v" * 64,
        redirect_uri=GoogleSettings.google_redirect_uri,
    )

    class FakeOAuthClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def exchange_code(self, **_kwargs):
            return GoogleTokenSet(
                access_token="calendar-access",
                refresh_token="calendar-refresh",
                expires_at=9_999_999_999,
                scope=all_google_scopes(),
            )

    class FakeGmailClient:
        def __init__(self, access_token: str):
            assert access_token == "calendar-access"

        async def profile(self):
            return {"emailAddress": "person@gmail.com"}

    monkeypatch.setattr(controller_module, "GoogleOAuthClient", FakeOAuthClient)
    monkeypatch.setattr(controller_module, "GoogleGmailClient", FakeGmailClient)
    result = asyncio.run(controller.complete_google(state=session.state, code="code"))
    assert result["purpose"] == "calendar"
    mailbox = next(iter(state_store.read()["mailboxes"].values()))
    assert mailbox["calendar_enabled"] is True
    assert mailbox["capabilities"] == ["mail", "calendar"]
    assert CALENDAR_EVENTS_SCOPE in mailbox["scope"]
    raw_state = state_store.path.read_text(encoding="utf-8")
    assert "calendar-access" not in raw_state
    assert "calendar-refresh" not in raw_state
    assert vault.contains(mailbox["credential_ref"])


def test_calendar_oauth_upgrade_rejects_partial_calendar_grant(tmp_path: Path, monkeypatch):
    controller, state_store, _ = make_controller(tmp_path)
    session = controller.sessions.create(
        provider="google",
        purpose="calendar",
        code_verifier="v" * 64,
        redirect_uri=GoogleSettings.google_redirect_uri,
    )

    class FakeOAuthClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def exchange_code(self, **_kwargs):
            return GoogleTokenSet(
                access_token="access",
                refresh_token="refresh",
                expires_at=9_999_999_999,
                scope=f"{GMAIL_SCOPE} {CALENDAR_EVENTS_SCOPE}",
            )

    monkeypatch.setattr(controller_module, "GoogleOAuthClient", FakeOAuthClient)
    with pytest.raises(RuntimeError, match="not fully granted"):
        asyncio.run(controller.complete_google(state=session.state, code="code"))
    assert not state_store.read().get("mailboxes")


def test_calendar_event_model_requires_timezone_and_valid_range():
    with pytest.raises(ValueError, match="timezone"):
        CalendarEventDraft(summary="Test", start="2026-08-21T10:00:00", end="2026-08-21T11:00:00")
    with pytest.raises(ValueError, match="after"):
        CalendarEventDraft(summary="Test", start="2026-08-21T11:00:00+02:00", end="2026-08-21T10:00:00+02:00")
    with pytest.raises(ValueError, match="attendee"):
        CalendarEventDraft(summary="Test", start="2026-08-21T10:00:00+02:00", end="2026-08-21T11:00:00+02:00", attendees=["not-an-email"])


def make_proposal(action: CalendarAction = CalendarAction.CREATE, *, event_id: str | None = None) -> CalendarProposal:
    event = None if action == CalendarAction.DELETE else CalendarEventDraft(
        summary="Projekttermin",
        start="2026-08-21T10:00:00+02:00",
        end="2026-08-21T11:00:00+02:00",
        attendees=["person@example.com"],
    )
    return CalendarProposal(
        action=action,
        mailbox_id="mb_google",
        calendar_id="primary",
        event_id=event_id,
        event=event,
        send_updates="all",
        reason="owner requested scheduling",
    )


def test_calendar_approval_store_is_atomic_and_never_direct(tmp_path: Path):
    store = CalendarApprovalStore(tmp_path / "calendar.db")
    approval = store.enqueue(make_proposal())
    assert approval["status"] == "pending"
    assert approval["execution_status"] == "not_applicable"
    assert approval["policy"]["requires_approval"] is True
    with pytest.raises(RuntimeError, match="approved"):
        store.claim(approval["approval_id"])
    store.decide(approval["approval_id"], decision="approved", actor="owner")
    claimed = store.claim(approval["approval_id"])
    assert claimed["execution_status"] == "executing"
    with pytest.raises(RuntimeError, match="already in progress"):
        store.claim(approval["approval_id"])
    completed = store.complete(approval["approval_id"], {"event_id": "evt_1"})
    assert completed["execution_status"] == "completed"
    assert completed["execution_result"]["event_id"] == "evt_1"


class FakeCalendarClient:
    def __init__(self):
        self.created = []
        self.updated = []
        self.deleted = []

    async def create_event(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "evt_created", "status": "confirmed", "htmlLink": "https://calendar.test/e"}

    async def update_event(self, **kwargs):
        self.updated.append(kwargs)
        return {"id": kwargs["event_id"], "status": "confirmed"}

    async def delete_event(self, **kwargs):
        self.deleted.append(kwargs)


def make_service(tmp_path: Path):
    scope = all_google_scopes()
    mailbox = {
        "mailbox_id": "mb_google",
        "connector": "gmail_api",
        "oauth_provider": "google",
        "email_address": "person@gmail.com",
        "scope": scope,
        "credential_ref": "unused",
        "capabilities": ["mail", "calendar"],
    }
    vault = CredentialVault(
        tmp_path / "secrets.vault",
        master_key_store=FileMasterKeyStore(tmp_path / "vault.key"),
    )
    service = CalendarService(
        store=CalendarApprovalStore(tmp_path / "calendar.db"),
        mailbox_lookup=lambda mailbox_id: mailbox if mailbox_id == "mb_google" else (_ for _ in ()).throw(KeyError(mailbox_id)),
        mailbox_supplier=lambda: [mailbox],
        vault=vault,
        google_client_id="client-id",
        google_client_secret="secret",
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )
    return service


@pytest.mark.asyncio
async def test_calendar_service_executes_only_after_owner_approval(tmp_path: Path, monkeypatch):
    service = make_service(tmp_path)
    fake = FakeCalendarClient()

    async def client(*_args, **_kwargs):
        return fake

    monkeypatch.setattr(service, "_client", client)
    approval = service.propose(CalendarProposalRequest(proposal=make_proposal(), actor="owner"))
    assert not fake.created
    result = await service.approve(approval["approval_id"], actor="owner")
    assert result["execution_status"] == "completed"
    assert len(fake.created) == 1
    assert fake.created[0]["send_updates"] == "all"
    assert fake.created[0]["event"]["attendees"] == [{"email": "person@example.com"}]


@pytest.mark.asyncio
async def test_calendar_update_and_delete_are_also_approval_gated(tmp_path: Path, monkeypatch):
    service = make_service(tmp_path)
    fake = FakeCalendarClient()

    async def client(*_args, **_kwargs):
        return fake

    monkeypatch.setattr(service, "_client", client)
    update = service.propose(CalendarProposalRequest(proposal=make_proposal(CalendarAction.UPDATE, event_id="evt_1")))
    delete = service.propose(CalendarProposalRequest(proposal=make_proposal(CalendarAction.DELETE, event_id="evt_2")))
    assert not fake.updated and not fake.deleted
    await service.approve(update["approval_id"], actor="owner")
    assert fake.updated[0]["event_id"] == "evt_1"
    service.reject(delete["approval_id"], actor="owner")
    assert not fake.deleted


def test_calendar_status_reports_connection_without_exposing_tokens(tmp_path: Path):
    service = make_service(tmp_path)
    status = service.status()
    assert status["write_requires_approval"] is True
    assert status["direct_write_allowed"] is False
    assert status["accounts"][0]["connected"] is True
    assert "credential_ref" not in status["accounts"][0]


def test_mail_action_schema_stays_mail_only():
    # Calendar does not extend the model-controlled MailActionType. This prevents a mail analysis
    # result from crossing directly into Calendar execution.
    assert all("calendar" not in action.value for action in MailActionType)
