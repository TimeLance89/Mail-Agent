from __future__ import annotations

import imaplib
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass(frozen=True)
class MailboxConfig:
    email_address: str
    username: str
    password: str
    imap_host: str
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465


class ImapMailbox:
    """Synchronous IMAP primitive used by the gateway's worker layer."""

    def __init__(self, config: MailboxConfig):
        self.config = config

    def _login(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(self.config.username, self.config.password)
        return client

    def test_connection(self) -> None:
        with self._login() as client:
            client.noop()

    def list_unseen_ids(self, folder: str = "INBOX") -> list[str]:
        with self._login() as client:
            client.select(folder, readonly=True)
            status, data = client.search(None, "UNSEEN")
            if status != "OK" or not data:
                return []
            return [item.decode("ascii") for item in data[0].split()]

    def fetch_rfc822(self, message_id: str, folder: str = "INBOX") -> bytes:
        with self._login() as client:
            client.select(folder, readonly=True)
            status, data = client.fetch(message_id, "(RFC822)")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                raise RuntimeError("Unable to fetch message")
            return data[0][1]

    def list_uids_after(self, last_uid: int, folder: str = "INBOX", limit: int = 100) -> list[int]:
        """Return stable IMAP UIDs newer than last_uid without changing seen state."""
        limit = max(1, min(limit, 1000))
        with self._login() as client:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            criterion = f"UID {max(1, last_uid + 1)}:*"
            status, data = client.uid("search", None, criterion)
            if status != "OK" or not data or not data[0]:
                return []
            uids = [int(item) for item in data[0].split()]
            return uids[:limit]

    def fetch_uid_rfc822(self, uid: int, folder: str = "INBOX") -> tuple[bytes, bool]:
        """Fetch one message by UID using PEEK so sync never marks it read."""
        with self._login() as client:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            status, data = client.uid("fetch", str(uid), "(BODY.PEEK[] FLAGS)")
            if status != "OK" or not data:
                raise RuntimeError(f"Unable to fetch IMAP UID {uid}")
            payload = next((item for item in data if isinstance(item, tuple)), None)
            if payload is None or not isinstance(payload[1], (bytes, bytearray)):
                raise RuntimeError(f"IMAP UID {uid} returned no RFC822 body")
            metadata = payload[0].decode("utf-8", "replace") if isinstance(payload[0], bytes) else str(payload[0])
            return bytes(payload[1]), "\\Seen" in metadata


class SmtpSender:
    def __init__(self, config: MailboxConfig):
        self.config = config

    def test_connection(self) -> None:
        if not self.config.smtp_host:
            raise ValueError("SMTP host is not configured")
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as smtp:
            smtp.login(self.config.username, self.config.password)
            smtp.noop()

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> None:
        if not self.config.smtp_host:
            raise ValueError("SMTP host is not configured")
        message = EmailMessage()
        message["From"] = self.config.email_address
        message["To"] = to
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        message.set_content(body)
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as smtp:
            smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)