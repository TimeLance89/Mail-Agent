from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.calendar_reliable import (
    CalendarConflictError,
    CalendarFreeSlotRequest,
    ReliableCalendarApprovalStore,
    ReliableCalendarProposalRequest,
    ReliableCalendarService,
)
from mail_agent_gateway.calendar_service import (
    CalendarAction,
    CalendarEventDraft,
    CalendarProposal,
)
from mail_agent_gateway.key_store import FileMasterKeyStore
from mail_agent_gateway.vault import CredentialVault
from mail_agent_google import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_FREEBUSY_SCOPE,
    CALENDAR_LIST_SCOPE,
)
from mail_agent_google.client import GMAIL_SCOPE


class FakeCalendarClient:
    def __init__(self):
        self.access_role = "owner"
        self.events: dict[str, dict] = {}
        self.listed_events: list[dict] = []
        self.busy: list[dict] = []
        self.fail_after_create = False
        self.created = 0
        self.updated = 0
        self.deleted = 0

    async def list_calendars(self):
        return [
            {
                "id": "owner@example.com",
                "summary": "Privat",
                "primary": True,
                "accessRole": self.access_role,
                "timeZone": "Europe/Berlin",
                "selected": True,
            }
        ]

    async def list_events(self, **_kwargs):
        return list(self.listed_events)

    async def freebusy(self, **_kwargs):
        return {"calendars": {"primary": {"busy": list(self.busy)}}}

    async def get_event(self, *, event_id: str, **_kwargs):
        event = self.events.get(event_id)
        if event is not None:
            return dict(event)
        request = httpx.Request("GET", f"https://calendar.test/{event_id}")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    async def create_event(self, *, event: dict, **_kwargs):
        self.created += 1
        stored = {
            **event,
            "etag": '"created-etag"',
            "status": "confirmed",
            "htmlLink": "https://calendar.test/event",
        }
        self.events[event["id"]] = stored
        if self.fail_after_create:
            self.fail_after_create = False
            raise httpx.ReadTimeout("response was lost after remote create")
        return dict(stored)

    async def update_event(self, *, event_id: str, patch: dict, etag: str | None, **_kwargs):
        assert self.events[event_id]["etag"] == etag
        self.updated += 1
        self.events[event_id] = {
            **self.events[event_id],
            **patch,
            "etag": '"updated-etag"',
            "status": "confirmed",
        }
        return dict(self.events[event_id])

    async def delete_event(self, *, event_id: str, etag: str | None, **_kwargs):
        assert self.events[event_id]["etag"] == etag
        self.deleted += 1
        del self.events[event_id]


def scope_string() -> str:
    return " ".join(
        [GMAIL_SCOPE, CALENDAR_EVENTS_SCOPE, CALENDAR_LIST_SCOPE, CALENDAR_FREEBUSY_SCOPE]
    )


def make_service(tmp_path: Path, fake: FakeCalendarClient) -> ReliableCalendarService:
    mailbox = {
        "mailbox_id": "mb_google",
        "connector": "gmail_api",
        "oauth_provider": "google",
        "email_address": "owner@example.com",
        "scope": scope_string(),
        "credential_ref": "unused",
        "capabilities": ["mail", "calendar"],
    }
    vault = CredentialVault(
        tmp_path / "secrets.vault",
        master_key_store=FileMasterKeyStore(tmp_path / "vault.key"),
    )
    service = ReliableCalendarService(
        store=ReliableCalendarApprovalStore(tmp_path / "calendar.db"),
        mailbox_lookup=lambda mailbox_id: mailbox
        if mailbox_id == "mb_google"
        else (_ for _ in ()).throw(KeyError(mailbox_id)),
        mailbox_supplier=lambda: [mailbox],
        vault=vault,
        google_client_id="client-id",
        google_client_secret="secret",
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    async def client(*_args, **_kwargs):
        return fake

    service._client = client  # type: ignore[method-assign]
    return service


def proposal(action=CalendarAction.CREATE, *, event_id: str | None = None) -> CalendarProposal:
    event = None
    if action != CalendarAction.DELETE:
        event = CalendarEventDraft(
            summary="Projekttermin",
            start="2026-08-24T10:00:00+02:00",
            end="2026-08-24T11:00:00+02:00",
        )
    return CalendarProposal(
        action=action,
        mailbox_id="mb_google",
        calendar_id="primary",
        event_id=event_id,
        event=event,
        send_updates="none",
        reason="owner requested",
    )


@pytest.mark.asyncio
async def test_free_slot_finder_uses_busy_intervals_and_work_hours(tmp_path: Path):
    fake = FakeCalendarClient()
    fake.busy = [
        {"start": "2026-08-24T08:00:00Z", "end": "2026-08-24T09:00:00Z"},
    ]
    service = make_service(tmp_path, fake)
    result = await service.find_free_slots(
        CalendarFreeSlotRequest(
            mailbox_id="mb_google",
            time_min="2026-08-24T07:00:00Z",
            time_max="2026-08-24T16:00:00Z",
            duration_minutes=60,
            workday_start="08:00",
            workday_end="18:00",
            time_zone="Europe/Berlin",
            max_results=3,
        )
    )
    starts = [item["start"] for item in result["slots"]]
    assert starts
    assert "2026-08-24T10:00:00+02:00" not in starts
    assert starts[0] == "2026-08-24T11:00:00+02:00"


@pytest.mark.asyncio
async def test_proposal_rejects_read_only_calendar(tmp_path: Path):
    fake = FakeCalendarClient()
    fake.access_role = "reader"
    service = make_service(tmp_path, fake)
    with pytest.raises(PermissionError, match="read-only"):
        await service.propose_checked(
            ReliableCalendarProposalRequest(proposal=proposal())
        )


@pytest.mark.asyncio
async def test_proposal_rejects_real_conflict_before_approval(tmp_path: Path):
    fake = FakeCalendarClient()
    fake.listed_events = [
        {
            "id": "evt_busy",
            "summary": "Schon belegt",
            "status": "confirmed",
            "start": {"dateTime": "2026-08-24T10:15:00+02:00"},
            "end": {"dateTime": "2026-08-24T10:45:00+02:00"},
        }
    ]
    service = make_service(tmp_path, fake)
    with pytest.raises(CalendarConflictError) as caught:
        await service.propose_checked(
            ReliableCalendarProposalRequest(proposal=proposal())
        )
    assert caught.value.conflicts[0]["id"] == "evt_busy"
    assert service.store.list("pending") == []


@pytest.mark.asyncio
async def test_create_retry_is_idempotent_after_lost_response(tmp_path: Path):
    fake = FakeCalendarClient()
    service = make_service(tmp_path, fake)
    approval = await service.propose_checked(
        ReliableCalendarProposalRequest(proposal=proposal())
    )
    fake.fail_after_create = True
    with pytest.raises(RuntimeError, match="could not be executed"):
        await service.approve(approval["approval_id"], actor="owner")
    failed = service.store.get(approval["approval_id"])
    assert failed["execution_status"] == "failed"
    assert fake.created == 1

    completed = await service.execute(approval["approval_id"])
    assert completed["execution_status"] == "completed"
    assert completed["execution_result"]["reconciled"] is True
    assert fake.created == 1
    assert len(fake.events) == 1


@pytest.mark.asyncio
async def test_update_fails_if_event_changed_after_owner_saw_approval(tmp_path: Path):
    fake = FakeCalendarClient()
    fake.events["evt_1"] = {
        "id": "evt_1",
        "etag": '"v1"',
        "summary": "Alt",
        "start": {"dateTime": "2026-08-24T09:00:00+02:00"},
        "end": {"dateTime": "2026-08-24T10:00:00+02:00"},
    }
    service = make_service(tmp_path, fake)
    approval = await service.propose_checked(
        ReliableCalendarProposalRequest(
            proposal=proposal(CalendarAction.UPDATE, event_id="evt_1")
        )
    )
    fake.events["evt_1"] = {
        **fake.events["evt_1"],
        "etag": '"v2"',
        "summary": "Von Google / anderem Client geändert",
    }
    with pytest.raises(RuntimeError, match="changed after approval"):
        await service.approve(approval["approval_id"], actor="owner")
    assert fake.updated == 0
    assert service.store.get(approval["approval_id"])["execution_status"] == "failed"


def test_stale_calendar_execution_is_recovered_as_safe_retry(tmp_path: Path):
    store = ReliableCalendarApprovalStore(tmp_path / "calendar.db")
    approval = store.enqueue(proposal())
    store.decide(approval["approval_id"], decision="approved", actor="owner")
    store.claim(approval["approval_id"])
    assert store.get(approval["approval_id"])["execution_status"] == "executing"
    assert store.recover_stale_executions() == 1
    recovered = store.get(approval["approval_id"])
    assert recovered["execution_status"] == "failed"
    assert "safe retry" in recovered["execution_error"]
