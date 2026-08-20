from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.calendar_concierge import CalendarConciergeRequest
from mail_agent_gateway.calendar_concierge_v171 import TargetedCalendarConcierge, _extract_explicit_datetime
from mail_agent_gateway.draft_lifecycle_v171 import discard_draft, install_active_draft_filter
from mail_agent_gateway.mail_store import MailStore


def test_explicit_weekend_datetime_is_parsed_in_calendar_timezone():
    zone = ZoneInfo("Europe/Berlin")
    parsed = _extract_explicit_datetime("Treffen am 22.08.2026 um 16:00 Uhr", zone)
    assert parsed == datetime(2026, 8, 22, 16, 0, tzinfo=zone)
    assert parsed.weekday() == 5


class FakeCalendarService:
    def __init__(self, *, busy: bool):
        self.busy = busy
        self.freebusy_requests = []
        self.slot_requests = []

    async def freebusy(self, request):
        self.freebusy_requests.append(request)
        if not self.busy:
            return {"calendars": {"primary": {"busy": []}}}
        return {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-08-22T16:00:00+02:00", "end": "2026-08-22T17:00:00+02:00"}
                    ]
                }
            }
        }

    async def events(self, *_args, **_kwargs):
        if not self.busy:
            return []
        return [
            {
                "id": "evt_busy",
                "summary": "Privater Termin",
                "start": {"dateTime": "2026-08-22T16:00:00+02:00"},
                "end": {"dateTime": "2026-08-22T17:00:00+02:00"},
            }
        ]

    async def find_free_slots(self, request):
        self.slot_requests.append(request)
        return {
            "slots": [
                {"start": "2026-08-22T14:00:00+02:00", "end": "2026-08-22T15:00:00+02:00", "duration_minutes": 60},
                {"start": "2026-08-22T17:00:00+02:00", "end": "2026-08-22T18:00:00+02:00", "duration_minutes": 60},
            ]
        }


def make_concierge(service):
    return TargetedCalendarConcierge(
        calendar_service=service,
        model_router=None,
        providers={},
        mail_store=None,
        state_store=None,
        identity_manager=None,
        policy_engine=None,
        audit_log=None,
    )


@pytest.mark.asyncio
async def test_concrete_mail_time_is_checked_directly_even_on_saturday():
    service = FakeCalendarService(busy=False)
    concierge = make_concierge(service)
    request = CalendarConciergeRequest(
        mailbox_id="mb_google",
        instruction="Prüfe diese Terminmail und hilf mir bei der Planung.",
        calendar_id="primary",
        duration_minutes=60,
    )
    check = await concierge._target_check(
        request,
        source_mail={"subject": "Treffen", "body": "22.08.2026 um 16:00 Uhr"},
        calendar_meta={"id": "primary", "timeZone": "Europe/Berlin"},
    )
    assert check is not None
    assert check["is_free"] is True
    assert check["start"] == "2026-08-22T16:00:00+02:00"
    assert service.freebusy_requests[0].time_min == "2026-08-22T16:00:00+02:00"
    assert service.freebusy_requests[0].time_max == "2026-08-22T17:00:00+02:00"
    assert service.slot_requests == []


@pytest.mark.asyncio
async def test_busy_weekend_request_gets_same_day_alternatives_not_previous_day():
    service = FakeCalendarService(busy=True)
    concierge = make_concierge(service)
    request = CalendarConciergeRequest(
        mailbox_id="mb_google",
        instruction="Prüfe diese Terminmail.",
        calendar_id="primary",
        duration_minutes=60,
    )
    check = await concierge._target_check(
        request,
        source_mail={"subject": "Treffen", "body": "22.08.2026 um 16:00 Uhr"},
        calendar_meta={"id": "primary", "timeZone": "Europe/Berlin"},
    )
    assert check is not None
    assert check["is_free"] is False
    assert check["conflicts"][0]["summary"] == "Privater Termin"
    assert service.slot_requests[0].weekdays == [5]
    assert all(item["start"].startswith("2026-08-22") for item in check["alternatives"])


def draft_proposal() -> MailActionProposal:
    return MailActionProposal(
        action=MailActionType.CREATE_DRAFT,
        mailbox_id="mb_1",
        message_id="m_1",
        recipient="person@example.com",
        subject="Antwort",
        body="Hallo",
        confidence=1.0,
    )


def test_discard_hides_plain_draft_but_keeps_audit_record(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    draft = store.create_draft(draft_proposal())
    install_active_draft_filter(store)
    result = discard_draft(store, audit, draft["draft_id"], actor="owner")
    assert result["status"] == "discarded"
    assert store.list_drafts() == []
    assert store.get_draft(draft["draft_id"])["status"] == "discarded"
    assert "draft_discarded" in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_discard_atomically_rejects_pending_send_approval(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    proposal = draft_proposal().model_copy(update={"action": MailActionType.SEND_REPLY})
    draft = store.create_draft(proposal)
    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="owner approval"),
    )
    store.link_draft_approval(draft["draft_id"], approval["approval_id"], source_action="send_reply")
    result = discard_draft(store, audit, draft["draft_id"], actor="owner")
    assert result["status"] == "discarded"
    decided = store.get_approval(approval["approval_id"])
    assert decided["status"] == "rejected"
    assert decided["decided_by"] == "owner"
    assert decided["execution_status"] == "not_applicable"


def test_discard_refuses_already_approved_outbound_action(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    proposal = draft_proposal().model_copy(update={"action": MailActionType.SEND_REPLY})
    draft = store.create_draft(proposal)
    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="owner approval"),
    )
    store.link_draft_approval(draft["draft_id"], approval["approval_id"], source_action="send_reply")
    store.decide_approval(approval["approval_id"], decision="approved", actor="owner")
    with pytest.raises(RuntimeError, match="bereits erteilt"):
        discard_draft(store, audit, draft["draft_id"], actor="owner")
