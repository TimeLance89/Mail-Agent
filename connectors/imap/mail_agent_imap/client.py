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
    """Small synchronous primitive; a worker layer will own retries and scheduling."""

    def __init__(self, config: MailboxConfig):
        self.config = config

    def test_connection(self) -> None:
        with imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port) as client:
            client.login(self.config.username, self.config.password)
            client.noop()

    def list_unseen_ids(self, folder: str = "INBOX") -> list[str]:
        with imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port) as client:
            client.login(self.config.username, self.config.password)
            client.select(folder, readonly=True)
            status, data = client.search(None, "UNSEEN")
            if status != "OK" or not data:
                return []
            return [item.decode("ascii") for item in data[0].split()]

    def fetch_rfc822(self, message_id: str, folder: str = "INBOX") -> bytes:
        with imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port) as client:
            client.login(self.config.username, self.config.password)
            client.select(folder, readonly=True)
            status, data = client.fetch(message_id, "(RFC822)")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                raise RuntimeError("Unable to fetch message")
            return data[0][1]


class SmtpSender:
    def __init__(self, config: MailboxConfig):
        self.config = config

    def test_connection(self) -> None:
        if not self.config.smtp_host:
            raise ValueError("SMTP host is not configured")
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as smtp:
            smtp.login(self.config.username, self.config.password)
            smtp.noop()

    def send(self, *, to: str, subject: str, body: str) -> None:
        if not self.config.smtp_host:
            raise ValueError("SMTP host is not configured")
        message = EmailMessage()
        message["From"] = self.config.email_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as smtp:
            smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)
