from __future__ import annotations

import asyncio
from typing import Any

from mail_agent_core.models import MailActionType

from .action_executor import MailActionExecutor
from .conversation_store import ConversationStore
from .mail_store import MailStore


class UndoService:
    """Undo a deliberately small subset of low-risk mailbox mutations.

    SEND, FORWARD, DELETE and arbitrary MOVE are intentionally excluded. Archive undo is only
    offered where the connector gives us a stable remote identifier (Gmail / Microsoft Graph).
    """

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        action_executor: MailActionExecutor,
        mail_store: MailStore,
    ) -> None:
        self.conversation_store = conversation_store
        self.action_executor = action_executor
        self.mail_store = mail_store

    @staticmethod
    def is_supported(source: dict[str, Any], action: MailActionType) -> bool:
        connector = str(source.get("connector") or "imap")
        if action == MailActionType.MARK_READ:
            return connector in {"gmail_api", "microsoft_graph", "imap", "smtp", ""}
        if action == MailActionType.ARCHIVE:
            return connector in {"gmail_api", "microsoft_graph"}
        return False

    async def undo(self, token: str) -> dict[str, Any]:
        item = self.conversation_store.get_undo(token)
        if item["status"] == "expired":
            raise RuntimeError("Undo-Zeitfenster ist abgelaufen")
        if item["status"] != "available":
            raise RuntimeError("Aktion wurde bereits rückgängig gemacht")
        payload = dict(item.get("payload") or {})
        source = dict(payload.get("source") or {})
        execution = dict(payload.get("execution") or {})
        action = MailActionType(item["action"])
        mailbox = self.action_executor.mailbox_lookup(item["mailbox_id"])
        connector = str(source.get("connector") or mailbox.get("connector") or "imap")
        message_key = str(source.get("remote_id") or source.get("internet_message_id") or source.get("uid") or item.get("message_id") or "")

        if action == MailActionType.MARK_READ:
            if connector == "gmail_api":
                remote_id = str(source.get("remote_id") or "")
                if not remote_id:
                    raise RuntimeError("Gmail-Nachricht besitzt keine Remote-ID")
                client = await self.action_executor._google_client(mailbox)
                await client.modify_message(remote_id, add_label_ids=["UNREAD"])
            elif connector == "microsoft_graph":
                remote_id = str(source.get("remote_id") or "")
                if not remote_id:
                    raise RuntimeError("Microsoft-Nachricht besitzt keine Remote-ID")
                client = await self.action_executor._microsoft_client(mailbox)
                await client.set_read(remote_id, False)
            else:
                uid = int(source["uid"])
                imap = self.action_executor._imap_runtime(mailbox)
                await asyncio.to_thread(imap.mark_unseen, uid)
            if message_key:
                self.mail_store.mark_message_seen(item["mailbox_id"], message_key, seen=False)

        elif action == MailActionType.ARCHIVE and connector == "gmail_api":
            remote_id = str(source.get("remote_id") or "")
            if not remote_id:
                raise RuntimeError("Gmail-Nachricht besitzt keine Remote-ID")
            client = await self.action_executor._google_client(mailbox)
            await client.modify_message(remote_id, add_label_ids=["INBOX"])

        elif action == MailActionType.ARCHIVE and connector == "microsoft_graph":
            remote_id = str(execution.get("remote_id") or source.get("remote_id") or "")
            if not remote_id:
                raise RuntimeError("Microsoft-Nachricht besitzt keine Remote-ID")
            client = await self.action_executor._microsoft_client(mailbox)
            await client.move_message(remote_id, "inbox")
        else:
            raise RuntimeError("Diese Aktion ist absichtlich nicht rückgängig machbar")

        self.conversation_store.complete_undo(token)
        return {
            "token": token,
            "status": "completed",
            "action": action.value,
            "mailbox_id": item["mailbox_id"],
            "resync_required": action == MailActionType.ARCHIVE,
        }
