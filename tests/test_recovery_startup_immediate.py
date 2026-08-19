from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.audit import AuditLog
from mail_agent_gateway.mail_store import MailStore
from mail_agent_gateway.recovery import RecoveryManager
from mail_agent_gateway.state import JsonStateStore


class EmptyVault:
    def contains(self, _reference: str) -> bool:
        return False


class HealthyProvider:
    async def health(self):
        class Health:
            available = True
            detail = "ready"

        return Health()


def test_startup_recovery_does_not_wait_before_protecting_against_duplicate_send(tmp_path):
    store = MailStore(tmp_path / "mail.db")
    identity = IdentityManager(tmp_path / "identity")
    identity.create(owner_id="owner", agent_name="Nova", usage_type="private")
    state = JsonStateStore(tmp_path / "state.json")
    state.write({"onboarding_completed": False})
    manager = RecoveryManager(
        data_dir=tmp_path,
        mail_store=store,
        identity_manager=identity,
        state_store=state,
        vault=EmptyVault(),
        providers={"test": HealthyProvider()},
        mailbox_supplier=lambda: [],
    )
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY,
        mailbox_id="mb1",
        message_id="m1",
        recipient="person@example.test",
        body="body",
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
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), approval["approval_id"]),
        )

    recovered = manager.recover_stale_executions()

    assert recovered["outbound_uncertain"] == 1
    assert store.get_approval(approval["approval_id"])["execution_status"] == "uncertain"
