from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType
from mail_agent_core.signature import assert_mandatory_agent_signature
from mail_agent_google import GoogleGmailClient
from mail_agent_imap import MailboxConfig, SmtpSender

from .audit import AuditLog
from .mail_store import MailStore
from .oauth_runtime import current_google_access_token
from .vault import CredentialVault


class MailActionExecutor:
    """Deterministic execution boundary for approved outbound mail actions.

    The LLM never reaches this class directly. Only a persisted, human-approved proposal can be
    claimed for execution. The mandatory MAIL-AGENT Ed25519 signature is revalidated immediately
    before any network call, and the database claim makes retries idempotent after a successful send.
    """

    def __init__(
        self,
        *,
        mail_store: MailStore,
        identity_manager: IdentityManager,
        vault: CredentialVault,
        mailbox_lookup: Callable[[str], dict[str, Any]],
        google_client_id: str,
        google_client_secret: str | None,
        audit_log: AuditLog,
    ) -> None:
        self.mail_store = mail_store
        self.identity_manager = identity_manager
        self.vault = vault
        self.mailbox_lookup = mailbox_lookup
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.audit_log = audit_log

    async def execute_approval(self, approval_id: str) -> dict[str, Any]:
        approval = self.mail_store.claim_approval_execution(approval_id)
        if approval.get("execution_status") == "sent":
            return approval

        try:
            proposal = MailActionProposal.model_validate(approval["proposal"])
            if proposal.action not in {MailActionType.SEND_REPLY, MailActionType.FORWARD}:
                raise RuntimeError("Only approved send_reply and forward actions are executable")
            if not proposal.message_id:
                raise RuntimeError("Approved outbound action has no source message")
            if not proposal.recipient:
                raise RuntimeError("Approved outbound action has no recipient")
            if not proposal.body:
                raise RuntimeError("Approved outbound action has no body")

            identity = self.identity_manager.load()
            metadata = proposal.metadata
            if metadata.get("agent_id") != identity.agent_id:
                raise RuntimeError("Approved message Agent-ID does not match this installation")
            if metadata.get("agent_fingerprint") != identity.fingerprint:
                raise RuntimeError("Approved message Agent-Fingerprint does not match this installation")
            if metadata.get("agent_signature_algorithm") != "ed25519":
                raise RuntimeError("Approved message does not use the mandatory Ed25519 signature")
            assert_mandatory_agent_signature(proposal.body, identity)

            mailbox = self.mailbox_lookup(proposal.mailbox_id)
            source = self.mail_store.get_message(proposal.mailbox_id, proposal.message_id)
            if source is None:
                raise RuntimeError("Source message is no longer available locally")
            if proposal.action == MailActionType.SEND_REPLY:
                expected_recipient = str(source.get("sender") or "").strip().lower()
                if proposal.recipient.strip().lower() != expected_recipient:
                    raise RuntimeError("Reply recipient no longer matches the authoritative source sender")

            result = await self._deliver(mailbox=mailbox, source=source, proposal=proposal)
            completed = self.mail_store.complete_approval_execution(approval_id, result)
            self.audit_log.append(
                "approved_mail_sent",
                details={
                    "approval_id": approval_id,
                    "mailbox_id": proposal.mailbox_id,
                    "action": proposal.action.value,
                    "recipient": proposal.recipient,
                    "connector": result.get("connector"),
                    "remote_id": result.get("remote_id"),
                },
            )
            return completed
        except Exception as exc:
            failed = self.mail_store.fail_approval_execution(approval_id, str(exc))
            self.audit_log.append(
                "approved_mail_send_failed",
                details={"approval_id": approval_id, "error": str(exc)},
            )
            raise RuntimeError(f"Approved mail could not be sent: {exc}") from exc

    async def _deliver(
        self,
        *,
        mailbox: dict[str, Any],
        source: dict[str, Any],
        proposal: MailActionProposal,
    ) -> dict[str, Any]:
        subject = proposal.subject or str(source.get("subject") or "")
        in_reply_to = str(source.get("internet_message_id") or "") or None
        references = in_reply_to
        connector = str(mailbox.get("connector") or "imap")

        if connector == "gmail_api":
            if not self.google_client_id:
                raise RuntimeError("Google OAuth is not configured in this MAIL-AGENT build")
            access_token = await current_google_access_token(
                mailbox,
                vault=self.vault,
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
            )
            payload = await GoogleGmailClient(access_token).send_message(
                from_address=mailbox["email_address"],
                to=proposal.recipient or "",
                subject=subject,
                body=proposal.body or "",
                thread_id=(source.get("remote_thread_id") if proposal.action == MailActionType.SEND_REPLY else None),
                in_reply_to=(in_reply_to if proposal.action == MailActionType.SEND_REPLY else None),
                references=(references if proposal.action == MailActionType.SEND_REPLY else None),
            )
            return {
                "connector": "gmail_api",
                "remote_id": payload.get("id"),
                "thread_id": payload.get("threadId"),
            }

        if connector not in {"imap", "smtp", ""}:
            raise RuntimeError(f"Outbound execution for connector {connector!r} is not implemented")
        credential_ref = mailbox.get("credential_ref")
        if not credential_ref or not self.vault.contains(credential_ref):
            raise RuntimeError("Mailbox credential is missing from the encrypted vault")
        password = self.vault.get_secret(credential_ref)
        config = MailboxConfig(
            email_address=mailbox["email_address"],
            username=mailbox["username"],
            password=password,
            imap_host=mailbox.get("imap_host", ""),
            imap_port=int(mailbox.get("imap_port", 993)),
            smtp_host=mailbox.get("smtp_host", ""),
            smtp_port=int(mailbox.get("smtp_port", 465)),
        )
        await asyncio.to_thread(
            SmtpSender(config).send,
            to=proposal.recipient or "",
            subject=subject,
            body=proposal.body or "",
            in_reply_to=(in_reply_to if proposal.action == MailActionType.SEND_REPLY else None),
            references=(references if proposal.action == MailActionType.SEND_REPLY else None),
        )
        return {"connector": "smtp", "remote_id": None, "thread_id": source.get("thread_key")}
