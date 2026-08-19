from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mail_agent_core.identity import IdentityManager
from mail_agent_core.models import MailActionProposal, MailActionType
from mail_agent_core.signature import assert_mandatory_agent_signature
from mail_agent_google import GoogleGmailClient
from mail_agent_imap import ImapMailbox, MailboxConfig, SmtpSender

from .audit import AuditLog
from .mail_store import MailStore
from .oauth_runtime import current_google_access_token
from .vault import CredentialVault


_SEND_ACTIONS = {MailActionType.SEND_REPLY, MailActionType.FORWARD}
_MAILBOX_ACTIONS = {
    MailActionType.MARK_READ,
    MailActionType.MOVE,
    MailActionType.ARCHIVE,
    MailActionType.DELETE,
}
_DIRECT_ACTIONS = {
    MailActionType.MARK_READ,
    MailActionType.MOVE,
    MailActionType.ARCHIVE,
}


class MailActionExecutor:
    """Deterministic network boundary for policy-approved email actions."""

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
        if approval.get("execution_status") in {"sent", "completed"}:
            return approval

        try:
            proposal = MailActionProposal.model_validate(approval["proposal"])
            result = await self._execute(proposal, require_outbound_signature=True)
            success_status = "sent" if proposal.action in _SEND_ACTIONS else "completed"
            completed = self.mail_store.complete_approval_execution(
                approval_id,
                result,
                success_status=success_status,
            )
            self.audit_log.append(
                "approved_action_executed",
                details={
                    "approval_id": approval_id,
                    "mailbox_id": proposal.mailbox_id,
                    "action": proposal.action.value,
                    "connector": result.get("connector"),
                    "remote_id": result.get("remote_id"),
                },
            )
            return completed
        except Exception as exc:
            self.mail_store.fail_approval_execution(approval_id, str(exc))
            self.audit_log.append(
                "approved_action_execution_failed",
                details={"approval_id": approval_id, "error": str(exc)},
            )
            raise RuntimeError(f"Approved action could not be executed: {exc}") from exc

    async def execute_direct(self, proposal: MailActionProposal) -> dict[str, Any]:
        """Execute only non-destructive mailbox actions after Policy Engine allowed them without approval."""
        if proposal.action not in _DIRECT_ACTIONS:
            raise RuntimeError("Action is not eligible for direct execution")
        result = await self._execute(proposal, require_outbound_signature=False)
        self.audit_log.append(
            "policy_allowed_action_executed",
            details={
                "mailbox_id": proposal.mailbox_id,
                "message_id": proposal.message_id,
                "action": proposal.action.value,
                "connector": result.get("connector"),
            },
        )
        return result

    async def _execute(
        self,
        proposal: MailActionProposal,
        *,
        require_outbound_signature: bool,
    ) -> dict[str, Any]:
        if proposal.action not in _SEND_ACTIONS | _MAILBOX_ACTIONS:
            raise RuntimeError(f"Action {proposal.action.value!r} has no remote executor")
        if not proposal.message_id:
            raise RuntimeError("Executable action has no source message")

        source = self.mail_store.get_message(proposal.mailbox_id, proposal.message_id)
        if source is None:
            raise RuntimeError("Source message is no longer available locally")
        mailbox = self.mailbox_lookup(proposal.mailbox_id)

        if proposal.action in _SEND_ACTIONS:
            if not require_outbound_signature:
                raise RuntimeError("Outbound mail cannot bypass approval execution")
            self._validate_outbound(proposal, source)
            return await self._deliver(mailbox=mailbox, source=source, proposal=proposal)

        return await self._mutate_mailbox(mailbox=mailbox, source=source, proposal=proposal)

    def _validate_outbound(self, proposal: MailActionProposal, source: dict[str, Any]) -> None:
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
        if proposal.action == MailActionType.SEND_REPLY:
            expected_recipient = str(source.get("sender") or "").strip().lower()
            if proposal.recipient.strip().lower() != expected_recipient:
                raise RuntimeError("Reply recipient no longer matches the authoritative source sender")

    async def _google_client(self, mailbox: dict[str, Any]) -> GoogleGmailClient:
        if not self.google_client_id:
            raise RuntimeError("Google OAuth is not configured in this MAIL-AGENT build")
        access_token = await current_google_access_token(
            mailbox,
            vault=self.vault,
            client_id=self.google_client_id,
            client_secret=self.google_client_secret,
        )
        return GoogleGmailClient(access_token)

    def _imap_runtime(self, mailbox: dict[str, Any]) -> ImapMailbox:
        credential_ref = mailbox.get("credential_ref")
        if not credential_ref or not self.vault.contains(credential_ref):
            raise RuntimeError("Mailbox credential is missing from the encrypted vault")
        password = self.vault.get_secret(credential_ref)
        return ImapMailbox(
            MailboxConfig(
                email_address=mailbox["email_address"],
                username=mailbox["username"],
                password=password,
                imap_host=mailbox.get("imap_host", ""),
                imap_port=int(mailbox.get("imap_port", 993)),
                smtp_host=mailbox.get("smtp_host", ""),
                smtp_port=int(mailbox.get("smtp_port", 465)),
            )
        )

    async def _mutate_mailbox(
        self,
        *,
        mailbox: dict[str, Any],
        source: dict[str, Any],
        proposal: MailActionProposal,
    ) -> dict[str, Any]:
        connector = str(mailbox.get("connector") or "imap")
        action = proposal.action
        message_key = str(source.get("remote_id") or source.get("internet_message_id") or source.get("uid"))

        if connector == "gmail_api":
            remote_id = source.get("remote_id")
            if not remote_id:
                raise RuntimeError("Gmail source message has no remote ID")
            client = await self._google_client(mailbox)
            destination = None
            if action == MailActionType.MARK_READ:
                await client.modify_message(remote_id, remove_label_ids=["UNREAD"])
                self.mail_store.mark_message_seen(proposal.mailbox_id, message_key)
            elif action == MailActionType.ARCHIVE:
                await client.modify_message(remote_id, remove_label_ids=["INBOX"])
                self.mail_store.remove_message(proposal.mailbox_id, message_key)
            elif action == MailActionType.MOVE:
                if not proposal.destination_folder:
                    raise RuntimeError("Move action has no destination folder")
                destination = await client.resolve_label_id(proposal.destination_folder)
                await client.modify_message(
                    remote_id,
                    add_label_ids=[destination],
                    remove_label_ids=["INBOX"],
                )
                self.mail_store.remove_message(proposal.mailbox_id, message_key)
            elif action == MailActionType.DELETE:
                await client.trash_message(remote_id)
                self.mail_store.remove_message(proposal.mailbox_id, message_key)
            else:
                raise RuntimeError("Unsupported Gmail mailbox action")
            return {
                "connector": "gmail_api",
                "action": action.value,
                "remote_id": remote_id,
                "destination": proposal.destination_folder if action == MailActionType.MOVE else destination,
            }

        if connector not in {"imap", "smtp", ""}:
            raise RuntimeError(f"Mailbox mutation for connector {connector!r} is not implemented")
        uid = int(source["uid"])
        imap = self._imap_runtime(mailbox)
        destination = None
        if action == MailActionType.MARK_READ:
            await asyncio.to_thread(imap.mark_seen, uid)
            self.mail_store.mark_message_seen(proposal.mailbox_id, message_key)
        elif action == MailActionType.ARCHIVE:
            destination = await asyncio.to_thread(imap.archive_uid, uid)
            self.mail_store.remove_message(proposal.mailbox_id, message_key)
        elif action == MailActionType.MOVE:
            if not proposal.destination_folder:
                raise RuntimeError("Move action has no destination folder")
            await asyncio.to_thread(imap.move_uid, uid, proposal.destination_folder)
            destination = proposal.destination_folder
            self.mail_store.remove_message(proposal.mailbox_id, message_key)
        elif action == MailActionType.DELETE:
            destination = await asyncio.to_thread(imap.trash_uid, uid)
            self.mail_store.remove_message(proposal.mailbox_id, message_key)
        else:
            raise RuntimeError("Unsupported IMAP mailbox action")
        return {
            "connector": "imap",
            "action": action.value,
            "remote_id": str(uid),
            "destination": destination,
        }

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
            client = await self._google_client(mailbox)
            payload = await client.send_message(
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
        imap = self._imap_runtime(mailbox)
        config = imap.config
        await asyncio.to_thread(
            SmtpSender(config).send,
            to=proposal.recipient or "",
            subject=subject,
            body=proposal.body or "",
            in_reply_to=(in_reply_to if proposal.action == MailActionType.SEND_REPLY else None),
            references=(references if proposal.action == MailActionType.SEND_REPLY else None),
        )
        return {"connector": "smtp", "remote_id": None, "thread_id": source.get("thread_key")}