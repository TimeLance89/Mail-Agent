from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mail_agent_core.agent import MailMessageContext
from mail_agent_core.models import ConversationStatus, MailActionProposal, MailActionType, MailCategory
from mail_agent_gateway.conversation_store import ConversationStore


def proposal(*, status=ConversationStatus.TO_REPLY, category=MailCategory.WORK):
    return MailActionProposal(action=MailActionType.READ, mailbox_id="mb", message_id="m2", thread_id="t1", confidence=.95, summary="summary", reason="reason", category=category, needs_reply=status==ConversationStatus.TO_REPLY, conversation_status=status, conversation_rationale="thread rationale")

def message(mid="m2"):
    return MailMessageContext(mailbox_id="mb", message_id=mid, thread_id="t1", sender="person@company.example", subject="Subject")

def test_thread_state_followup_and_snooze(tmp_path):
    store=ConversationStore(tmp_path/"conversation.db")
    item=store.record_analysis(message=message(), proposal=proposal(), decision_path=[{"stage":"policy","result":"allowed"}], to_reply_days=2, awaiting_reply_days=4)
    assert item["status"]=="to_reply"
    assert item["due_at"]
    until=(datetime.now(UTC)+timedelta(days=2)).isoformat()
    store.snooze("mb","t1",until)
    assert store.list_threads(mailbox_id="mb", status="to_reply")==[]
    assert store.list_threads(mailbox_id="mb", status="to_reply", include_snoozed=True)[0]["snoozed_until"]==until

def test_outbound_moves_thread_to_awaiting_reply(tmp_path):
    store=ConversationStore(tmp_path/"conversation.db")
    store.record_analysis(message=message(), proposal=proposal(), decision_path=[], to_reply_days=2, awaiting_reply_days=4)
    item=store.mark_outbound_sent(mailbox_id="mb", thread_id="t1", source_message_id="m2", recipient="person@company.example", subject="Re: Subject", awaiting_reply_days=4)
    assert item["status"]=="awaiting_reply"
    assert item["due_at"]

def test_sender_pattern_is_conservative_and_deduplicated(tmp_path):
    store=ConversationStore(tmp_path/"conversation.db")
    suggestion=None
    for i in range(6):
        suggestion=store.record_sender_observation(mailbox_id="mb", message_id=f"m{i}", sender="newsletter@vendor.example", category="newsletter", min_samples=6, confidence_threshold=.9)
    assert suggestion and suggestion["confidence"]==1.0
    # Same message cannot inflate confidence.
    assert store.record_sender_observation(mailbox_id="mb", message_id="m5", sender="newsletter@vendor.example", category="newsletter", min_samples=6, confidence_threshold=.9) is None
    store.decide_pattern("mb","newsletter@vendor.example","newsletter",status="rejected")
    assert store.list_pattern_suggestions(mailbox_id="mb")==[]

def test_public_mail_domains_never_create_sender_pattern(tmp_path):
    store=ConversationStore(tmp_path/"conversation.db")
    for i in range(8):
        store.record_sender_observation(mailbox_id="mb", message_id=f"p{i}", sender="someone@gmail.com", category="advertising", min_samples=6, confidence_threshold=.9)
    assert store.list_pattern_suggestions(mailbox_id="mb")==[]
