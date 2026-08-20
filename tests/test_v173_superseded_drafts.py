from __future__ import annotations

from pathlib import Path

from mail_agent_core.models import MailActionProposal, MailActionType
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.calendar_followup_v172 import _discard_superseded_source_drafts
from mail_agent_gateway.mail_store import MailStore


def _proposal(*, calendar_confirmation: bool = False) -> MailActionProposal:
    metadata = {"calendar_confirmation": True} if calendar_confirmation else {}
    return MailActionProposal(
        action=MailActionType.CREATE_DRAFT,
        mailbox_id="mb_1",
        message_id="msg_1",
        thread_id="thread_1",
        recipient="requester@example.org",
        subject="Re: Treffen",
        body="Test",
        confidence=1.0,
        metadata=metadata,
    )


def test_accepted_calendar_work_supersedes_only_preliminary_source_drafts(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    preliminary = store.create_draft(_proposal())
    confirmation = store.create_draft(_proposal(calendar_confirmation=True))

    discarded = _discard_superseded_source_drafts(
        store,
        audit,
        mailbox_id="mb_1",
        source_message_id="msg_1",
        actor="autonomous-agent",
    )

    assert discarded == 1
    assert store.get_draft(preliminary["draft_id"])["status"] == "discarded"
    assert store.get_draft(confirmation["draft_id"])["status"] == "draft"
