from __future__ import annotations

import hashlib
import html
import re

import httpx
from mail_agent_google import GoogleGmailClient
from mail_agent_google.client import stable_remote_uid as google_uid
from mail_agent_microsoft import MicrosoftGraphClient
from mail_agent_microsoft.client import stable_remote_uid as microsoft_uid

from .mail_store import MailStore, StoredMessage
from .sync import parse_message


class GoogleGmailSyncService:
    def __init__(self, store: MailStore):
        self.store = store

    async def sync(self, *, mailbox_id: str, access_token: str, limit: int = 100) -> dict:
        client = GoogleGmailClient(access_token)
        status = self.store.sync_status(mailbox_id)
        history_id = status.get("cursor")
        if history_id:
            try:
                return await self._partial(client, mailbox_id, history_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
        return await self._full(client, mailbox_id, limit)

    async def _full(self, client: GoogleGmailClient, mailbox_id: str, limit: int) -> dict:
        message_ids = await client.list_message_ids(max_results=limit, label_id="INBOX")
        stored: list[StoredMessage] = []
        newest_history: str | None = None
        for message_id in message_ids:
            payload = await client.get_raw_message(message_id)
            if "INBOX" not in payload.get("labelIds", []):
                continue
            parsed = parse_message(
                mailbox_id,
                google_uid(message_id),
                payload["raw_bytes"],
                seen="UNREAD" not in payload.get("labelIds", []),
            )
            stored.append(
                StoredMessage(
                    **{
                        **parsed.__dict__,
                        "remote_id": message_id,
                        "remote_thread_id": payload.get("threadId"),
                        "connector": "gmail_api",
                    }
                )
            )
            newest_history = newest_history or payload.get("historyId")
        if newest_history is None:
            newest_history = str((await client.profile()).get("historyId", "")) or None
        self.store.upsert_messages(stored)
        self.store.record_sync(
            mailbox_id,
            last_uid=max((item.uid for item in stored), default=0),
            error=None,
            cursor=newest_history,
        )
        return {"mailbox_id": mailbox_id, "connector": "gmail_api", "fetched": len(stored), "cursor": newest_history}

    async def _partial(self, client: GoogleGmailClient, mailbox_id: str, history_id: str) -> dict:
        page_token: str | None = None
        changed_ids: set[str] = set()
        deleted_ids: set[str] = set()
        newest_history = history_id
        while True:
            payload = await client.history(start_history_id=history_id, page_token=page_token)
            newest_history = str(payload.get("historyId", newest_history))
            for record in payload.get("history", []):
                for item in record.get("messagesAdded", []):
                    changed_ids.add(item.get("message", {}).get("id", ""))
                for item in record.get("labelsAdded", []):
                    changed_ids.add(item.get("message", {}).get("id", ""))
                for item in record.get("labelsRemoved", []):
                    changed_ids.add(item.get("message", {}).get("id", ""))
                for item in record.get("messagesDeleted", []):
                    remote_id = item.get("message", {}).get("id", "")
                    if remote_id:
                        deleted_ids.add(remote_id)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        changed_ids.discard("")
        stored: list[StoredMessage] = []
        for remote_id in changed_ids - deleted_ids:
            try:
                payload = await client.get_raw_message(remote_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    deleted_ids.add(remote_id)
                    continue
                raise
            if "INBOX" not in payload.get("labelIds", []):
                deleted_ids.add(remote_id)
                continue
            parsed = parse_message(
                mailbox_id,
                google_uid(remote_id),
                payload["raw_bytes"],
                seen="UNREAD" not in payload.get("labelIds", []),
            )
            stored.append(
                StoredMessage(
                    **{
                        **parsed.__dict__,
                        "remote_id": remote_id,
                        "remote_thread_id": payload.get("threadId"),
                        "connector": "gmail_api",
                    }
                )
            )
        self.store.upsert_messages(stored)
        for remote_id in deleted_ids:
            self.store.delete_remote_message(mailbox_id, remote_id)
        last_uid = self.store.get_last_uid(mailbox_id)
        self.store.record_sync(mailbox_id, last_uid=last_uid, error=None, cursor=newest_history)
        return {
            "mailbox_id": mailbox_id,
            "connector": "gmail_api",
            "fetched": len(stored),
            "removed": len(deleted_ids),
            "cursor": newest_history,
        }


class MicrosoftGraphSyncService:
    def __init__(self, store: MailStore):
        self.store = store

    async def sync(self, *, mailbox_id: str, access_token: str) -> dict:
        client = MicrosoftGraphClient(access_token)
        cursor = self.store.sync_status(mailbox_id).get("cursor")
        url = cursor or None
        stored_count = 0
        removed_count = 0
        final_delta: str | None = None
        for _ in range(100):
            payload = await client.delta(url)
            messages: list[StoredMessage] = []
            for item in payload.get("value", []):
                remote_id = item.get("id")
                if not remote_id:
                    continue
                if "@removed" in item:
                    removed_count += int(self.store.delete_remote_message(mailbox_id, remote_id))
                    continue
                messages.append(_graph_message(mailbox_id, item))
            stored_count += self.store.upsert_messages(messages)
            next_link = payload.get("@odata.nextLink")
            final_delta = payload.get("@odata.deltaLink") or final_delta
            if next_link:
                url = next_link
                continue
            break
        else:
            raise RuntimeError("Microsoft Graph delta sync exceeded 100 pages")
        if not final_delta:
            raise RuntimeError("Microsoft Graph delta sync completed without a deltaLink")
        self.store.record_sync(
            mailbox_id,
            last_uid=self.store.get_last_uid(mailbox_id),
            error=None,
            cursor=final_delta,
        )
        return {
            "mailbox_id": mailbox_id,
            "connector": "microsoft_graph",
            "fetched": stored_count,
            "removed": removed_count,
            "cursor": "delta-link",
        }


def _graph_message(mailbox_id: str, item: dict) -> StoredMessage:
    remote_id = item["id"]
    sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address", "")
    recipients = []
    for field in ("toRecipients", "ccRecipients"):
        for recipient in item.get(field, []) or []:
            address = (recipient.get("emailAddress") or {}).get("address")
            if address:
                recipients.append(address)
    body = (item.get("body") or {}).get("content", "") or ""
    if (item.get("body") or {}).get("contentType", "text").lower() == "html":
        body = _strip_html(body)
    conversation_id = item.get("conversationId") or remote_id
    thread_key = hashlib.sha256(conversation_id.encode("utf-8", "replace")).hexdigest()[:32]
    return StoredMessage(
        mailbox_id=mailbox_id,
        uid=microsoft_uid(remote_id),
        internet_message_id=item.get("internetMessageId"),
        thread_key=thread_key,
        sender=sender,
        recipients=recipients,
        subject=item.get("subject") or "",
        sent_at=item.get("sentDateTime") or item.get("receivedDateTime"),
        body_text=body.strip(),
        seen=bool(item.get("isRead", False)),
        remote_id=remote_id,
        remote_thread_id=conversation_id,
        connector="microsoft_graph",
    )


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()