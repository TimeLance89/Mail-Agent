from pathlib import Path

from mail_agent_core.models import MailActionProposal, MailActionType, PolicyDecision
from mail_agent_gateway.mail_store import MailStore


def test_send_approval_moves_ready_executing_failed_and_can_retry(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    proposal = MailActionProposal(
        action=MailActionType.SEND_REPLY,
        mailbox_id="mb",
        message_id="msg",
        recipient="person@example.test",
        subject="Re: Hello",
        body="signed body placeholder",
        confidence=0.9,
    )
    approval = store.enqueue_approval(
        proposal,
        PolicyDecision(allowed=True, requires_approval=True, risk="high", reason="send"),
    )

    approved = store.decide_approval(approval["approval_id"], decision="approved", actor="user")
    assert approved["execution_status"] == "ready"

    claimed = store.claim_approval_execution(approval["approval_id"])
    assert claimed["execution_status"] == "executing"

    failed = store.fail_approval_execution(approval["approval_id"], "temporary SMTP failure")
    assert failed["execution_status"] == "failed"
    assert "SMTP" in failed["execution_error"]

    retried = store.claim_approval_execution(approval["approval_id"])
    assert retried["execution_status"] == "executing"

    sent = store.complete_approval_execution(
        approval["approval_id"],
        {"connector": "smtp", "remote_id": None},
    )
    assert sent["execution_status"] == "sent"

    idempotent = store.claim_approval_execution(approval["approval_id"])
    assert idempotent["execution_status"] == "sent"
