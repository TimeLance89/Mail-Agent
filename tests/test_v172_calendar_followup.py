from __future__ import annotations

from pathlib import Path

import pytest

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import AgentProfile, AutonomyMode, UsageType
from mail_agent_core.policy import PolicyEngine
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.calendar_followup_v172 import prepare_calendar_confirmation_followup
from mail_agent_gateway.draft_service import DraftService
from mail_agent_gateway.mail_store import MailStore, StoredMessage
from mail_agent_gateway.state import JsonStateStore


class OfflineCalendarConcierge:
    async def _provider(self):
        raise RuntimeError("model offline")


def _runtime(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    state = JsonStateStore(tmp_path / "state.json")
    profile = AgentProfile(
        owner_id="owner_1",
        agent_name="Nova",
        usage_type=UsageType.PRIVATE,
        autonomy_mode=AutonomyMode.ASSISTANT,
        language="de",
        email_signature="Viele Grüße\nSteffen",
    )
    state.write(
        {
            "onboarding_completed": True,
            "configuration": {"profile": profile.model_dump(mode="json")},
        }
    )
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner_1", agent_name="Nova", usage_type="private")
    audit = AuditLog(tmp_path / "audit.jsonl")
    policy = PolicyEngine()
    drafts = DraftService(
        mail_store=store,
        identity_manager=identity,
        state_store=state,
        policy_engine=policy,
        audit_log=audit,
    )
    store.upsert_messages(
        [
            StoredMessage(
                mailbox_id="mb_1",
                uid=1,
                internet_message_id="<meeting@example.com>",
                thread_key="thread_1",
                sender="requester@example.com",
                recipients=["owner@example.com"],
                subject="Treffen",
                sent_at="2026-08-20T10:00:00+02:00",
                body_text="Passt dir der 22.08.2026 um 16:00 Uhr?",
                seen=False,
                remote_id="msg_1",
                remote_thread_id="thread_remote_1",
                connector="gmail_api",
            )
        ]
    )
    return store, drafts, identity, policy, audit


def _calendar_approval():
    return {
        "approval_id": "calapr_accepted",
        "mailbox_id": "mb_1",
        "action": "create",
        "status": "approved",
        "execution_status": "completed",
        "execution_result": {"id": "evt_accepted"},
        "proposal": {
            "action": "create",
            "mailbox_id": "mb_1",
            "calendar_id": "primary",
            "source_message_id": "msg_1",
            "send_updates": "none",
            "event": {
                "summary": "Treffen",
                "start": "2026-08-22T16:00:00+02:00",
                "end": "2026-08-22T17:00:00+02:00",
                "time_zone": "Europe/Berlin",
                "attendees": [],
            },
        },
    }


@pytest.mark.asyncio
async def test_calendar_acceptance_creates_signed_reply_and_pending_send_approval(tmp_path: Path):
    store, drafts, identity, policy, audit = _runtime(tmp_path)
    result = await prepare_calendar_confirmation_followup(
        _calendar_approval(),
        mail_store=store,
        draft_service=drafts,
        calendar_concierge=OfflineCalendarConcierge(),
        identity_manager=identity,
        policy_engine=policy,
        audit_log=audit,
        actor="local-user",
    )
    assert result is not None
    assert result["draft"]["status"] == "approval_pending"
    assert result["approval"]["status"] == "pending"
    assert result["approval"]["action"] == "send_reply"
    assert result["approval"]["proposal"]["recipient"] == "requester@example.com"
    assert "22.08.2026" in result["approval"]["proposal"]["body"]
    metadata = result["approval"]["proposal"]["metadata"]
    assert metadata["calendar_confirmation"] is True
    assert metadata["calendar_source_approval_id"] == "calapr_accepted"
    assert metadata["agent_signature_algorithm"] == "ed25519"
    assert metadata["agent_message_signature"]


@pytest.mark.asyncio
async def test_calendar_acceptance_followup_is_idempotent(tmp_path: Path):
    store, drafts, identity, policy, audit = _runtime(tmp_path)
    kwargs = {
        "mail_store": store,
        "draft_service": drafts,
        "calendar_concierge": OfflineCalendarConcierge(),
        "identity_manager": identity,
        "policy_engine": policy,
        "audit_log": audit,
        "actor": "local-user",
    }
    first = await prepare_calendar_confirmation_followup(_calendar_approval(), **kwargs)
    second = await prepare_calendar_confirmation_followup(_calendar_approval(), **kwargs)
    assert first is not None and second is not None
    assert first["draft"]["draft_id"] == second["draft"]["draft_id"]
    assert first["approval"]["approval_id"] == second["approval"]["approval_id"]
    with store._lock, store._connect() as conn:  # noqa: SLF001 - regression assertion
        count = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    assert count == 1


def test_v172_workbench_contract_remains_exposed_in_0180_bundle():
    root = Path(__file__).resolve().parents[1]
    index = (root / "apps/web/index.html").read_text(encoding="utf-8")
    ux = (root / "apps/web/v172-ux.js").read_text(encoding="utf-8")
    entry = (root / "apps/launcher/mail_agent_launcher_entry.py").read_text(encoding="utf-8")
    gateway = (root / "apps/gateway/mail_agent_gateway/main_v172.py").read_text(encoding="utf-8")

    assert "/assets/v172-ux.js?v=0.18.1" in index
    assert "data.draftDiscard" in ux or "draftDiscard" in ux
    assert "/discard" in ux
    assert "prepare-mail-reply" in ux
    assert "Freigeben & senden" in ux
    assert "fetch('/health'" in ux
    assert "MutationObserver" not in ux
    assert "mail_agent_launcher.v180_entry" in entry
    assert "_approve_with_confirmation_reply" in gateway
    assert "mail_followup_required" in gateway
    assert "writerwithoutprivateaccess" in gateway
