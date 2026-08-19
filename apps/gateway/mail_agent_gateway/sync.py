from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from mail_agent_imap import ImapMailbox, MailboxConfig

from .mail_store import MailStore, StoredMessage
from .vault import CredentialVault


@dataclass(frozen=True)
class MailboxRuntimeConfig:
    mailbox_id: str
    email_address: str
    username: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    credential_ref: str


class MailSyncService:
    def __init__(self, store: MailStore, vault: CredentialVault):
        self.store = store
        self.vault = vault
        self._locks: dict[str, asyncio.Lock] = {}

    async def sync(self, config: MailboxRuntimeConfig, *, limit: int = 100) -> dict:
        lock = self._locks.setdefault(config.mailbox_id, asyncio.Lock())
        async with lock:
            password = self.vault.get_secret(config.credential_ref)
            mailbox = ImapMailbox(
                MailboxConfig(
                    email_address=config.email_address,
                    username=config.username,
                    password=password,
                    imap_host=config.imap_host,
                    imap_port=config.imap_port,
                    smtp_host=config.smtp_host,
                    smtp_port=config.smtp_port,
                )
            )
            last_uid = self.store.get_last_uid(config.mailbox_id)
            try:
                uids = await asyncio.to_thread(mailbox.list_uids_after, last_uid, "INBOX", limit)
                stored: list[StoredMessage] = []
                max_uid = last_uid
                for uid in uids:
                    raw, seen = await asyncio.to_thread(mailbox.fetch_uid_rfc822, uid, "INBOX")
                    stored.append(parse_message(config.mailbox_id, uid, raw, seen=seen))
                    max_uid = max(max_uid, uid)
                self.store.upsert_messages(stored)
                self.store.record_sync(config.mailbox_id, last_uid=max_uid, error=None)
                return {
                    "mailbox_id": config.mailbox_id,
                    "fetched": len(stored),
                    "last_uid": max_uid,
                }
            except Exception as exc:
                self.store.record_sync(config.mailbox_id, last_uid=last_uid, error=str(exc))
                raise


def parse_message(mailbox_id: str, uid: int, raw: bytes, *, seen: bool) -> StoredMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = _first_address(message.get_all("From", []))
    recipients = [address for _, address in getaddresses(message.get_all("To", []) + message.get_all("Cc", [])) if address]
    subject = str(message.get("Subject", ""))
    internet_message_id = str(message.get("Message-ID")) if message.get("Message-ID") else None
    references = " ".join(str(value) for value in message.get_all("References", []))
    in_reply_to = str(message.get("In-Reply-To", ""))
    thread_seed = _thread_seed(internet_message_id, references, in_reply_to, subject, sender)
    sent_at = _parse_date(message)
    body = _extract_text(message)
    return StoredMessage(
        mailbox_id=mailbox_id,
        uid=uid,
        internet_message_id=internet_message_id,
        thread_key=hashlib.sha256(thread_seed.encode("utf-8", "replace")).hexdigest()[:32],
        sender=sender,
        recipients=recipients,
        subject=subject,
        sent_at=sent_at,
        body_text=body,
        seen=seen,
    )


def _first_address(values: list[str]) -> str:
    parsed = getaddresses(values)
    return parsed[0][1] if parsed else ""


def _thread_seed(
    message_id: str | None,
    references: str,
    in_reply_to: str,
    subject: str,
    sender: str,
) -> str:
    ids = re.findall(r"<[^>]+>", references + " " + in_reply_to)
    if ids:
        return ids[0].lower()
    if message_id:
        return message_id.strip().lower()
    normalized_subject = re.sub(r"^(?:(?:re|fw|fwd):\s*)+", "", subject, flags=re.I).strip().lower()
    return f"{normalized_subject}|{sender.lower()}"


def _parse_date(message: Message) -> str | None:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(str(raw)).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _extract_text(message: Message) -> str:
    if message.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                content = part.get_content()
            except Exception:
                continue
            if not isinstance(content, str):
                continue
            (plain_parts if content_type == "text/plain" else html_parts).append(content)
        if plain_parts:
            return "\n\n".join(plain_parts).strip()
        return _strip_html("\n\n".join(html_parts)).strip()
    try:
        content = message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode("utf-8", "replace")
    if not isinstance(content, str):
        return ""
    return _strip_html(content).strip() if message.get_content_type() == "text/html" else content.strip()


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value)