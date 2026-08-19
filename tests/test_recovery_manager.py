from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.mail_store import MailStore
from mail_agent_gateway.recovery import RecoveryManager
from mail_agent_gateway.state import JsonStateStore


class FakeVault:
    def __init__(self, refs=()):
        self.refs = set(refs)

    def contains(self, reference: str) -> bool:
        return reference in self.refs


class HealthyProvider:
    async def health(self):
        class Health:
            available = True
            detail = "ready"

        return Health()


def make_manager(tmp_path, *, mailboxes=None, vault_refs=()):
    store = MailStore(tmp_path / "mail.db")
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner", agent_name="Nova", usage_type="private")
    state = JsonStateStore(tmp_path / "state.json")
    state.write(
        {
            "onboarding_completed": True,
            "configuration": {
                "provider": "test",
                "model": "model",
                "profile": {
                    "owner_id": "owner",
                    "agent_name": "Nova",
                    "usage_type": "private",
                },
            },
        }
    )
    boxes = mailboxes or []
    manager = RecoveryManager(
        data_dir=tmp_path,
        mail_store=store,
        identity_manager=identity,
        state_store=state,
        vault=FakeVault(vault_refs),
        providers={"test": HealthyProvider()},
        mailbox_supplier=lambda: boxes,
    )
    return manager, store


def stale_approval(store: MailStore, action: MailActionType) -> str:
    proposal = MailActionProposal(
        action=action,
        mailbox_id="mb1",
        message_id="m1",
        recipient="person@example.test" if action in {MailActionType.SEND_REPLY, MailActionType.FORWARD} else None,
        body="signed body" if action in {MailActionType.SEND_REPLY, MailActionType.FORWARD} else None,
        confidence=0.99,
    )
    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="test"),
    )
    store.decide_approval(approval["approval_id"], decision="approved", actor="owner")
    with store._lock, store._connect() as conn:
        conn.execute(
            """
            UPDATE approvals
            SET execution_status='executing', execution_started_at=?
            WHERE approval_id=?
            """,
            ((datetime.now(UTC) - timedelta(minutes=20)).isoformat(), approval["approval_id"]),
        )
    return approval["approval_id"]


def test_stale_outbound_becomes_uncertain_instead_of_automatic_retry(tmp_path):
    manager, store = make_manager(tmp_path)
    approval_id = stale_approval(store, MailActionType.SEND_REPLY)

    recovered = manager.recover_stale_executions(max_age_seconds=60)

    assert recovered == {"outbound_uncertain": 1, "retryable_failed": 0}
    approval = store.get_approval(approval_id)
    assert approval["execution_status"] == "uncertain"
    assert "Gesendet-Ordner" in approval["execution_error"]


def test_stale_non_outbound_is_retryable(tmp_path):
    manager, store = make_manager(tmp_path)
    approval_id = stale_approval(store, MailActionType.DELETE)

    recovered = manager.recover_stale_executions(max_age_seconds=60)

    assert recovered == {"outbound_uncertain": 0, "retryable_failed": 1}
    assert store.get_approval(approval_id)["execution_status"] == "failed"


def test_owner_can_reconcile_uncertain_send_as_sent_or_retry(tmp_path):
    manager, store = make_manager(tmp_path)
    sent_id = stale_approval(store, MailActionType.SEND_REPLY)
    retry_id = stale_approval(store, MailActionType.FORWARD)
    manager.recover_stale_executions(max_age_seconds=60)

    sent = manager.reconcile_uncertain(sent_id, outcome="already_sent")
    retry = manager.reconcile_uncertain(retry_id, outcome="retry")

    assert sent["execution_status"] == "sent"
    assert retry["execution_status"] == "ready"


def test_diagnostics_report_provider_storage_database_identity_and_mailbox(tmp_path):
    mailboxes = [
        {
            "mailbox_id": "mb1",
            "email_address": "owner@example.test",
            "credential_ref": "oauth:mb1",
        }
    ]
    manager, _store = make_manager(tmp_path, mailboxes=mailboxes, vault_refs={"oauth:mb1"})

    report = asyncio.run(manager.report())

    assert report["overall"] == "ok"
    ids = {item["id"] for item in report["checks"]}
    assert {"storage", "database", "identity", "provider", "execution", "queue"} <= ids
    assert "mailbox:mb1" in ids


def test_diagnostics_marks_missing_vault_credential_as_action_required(tmp_path):
    mailboxes = [
        {
            "mailbox_id": "mb1",
            "email_address": "owner@example.test",
            "credential_ref": "oauth:missing",
        }
    ]
    manager, _store = make_manager(tmp_path, mailboxes=mailboxes)

    report = asyncio.run(manager.report())
    mailbox = next(item for item in report["checks"] if item["id"] == "mailbox:mb1")

    assert report["overall"] == "action_required"
    assert mailbox["status"] == "error"
    assert mailbox["action"] == "reconnect_mailbox"
