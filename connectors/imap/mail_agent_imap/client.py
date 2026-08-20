from __future__ import annotations

import imaplib
import re
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


@dataclass(frozen=True)
class ImapFolder:
    name: str
    flags: frozenset[str]


class ImapMailbox:
    """Synchronous IMAP primitive used by the gateway's worker layer."""

    def __init__(self, config: MailboxConfig):
        self.config = config

    def _login(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        client.login(self.config.username, self.config.password)
        return client

    @staticmethod
    def _quote_mailbox(value: str) -> str:
        if not value or "\r" in value or "\n" in value:
            raise ValueError("Invalid IMAP folder name")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _parse_folder(raw: bytes | str) -> ImapFolder | None:
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        match = re.match(r"^\((?P<flags>[^)]*)\)\s+(?:\"[^\"]*\"|NIL)\s+(?P<name>.+)$", text.strip())
        if not match:
            return None
        name = match.group("name").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        flags = frozenset(part.casefold() for part in match.group("flags").split())
        return ImapFolder(name=name, flags=flags)

    def list_folders(self) -> list[ImapFolder]:
        with self._login() as client:
            status, rows = client.list()
            if status != "OK" or not rows:
                raise RuntimeError("Unable to list IMAP folders")
            return [folder for row in rows if row and (folder := self._parse_folder(row)) is not None]

    def resolve_folder(self, name: str) -> str:
        wanted = name.strip().casefold()
        if not wanted:
            raise ValueError("Destination folder is empty")
        for folder in self.list_folders():
            if folder.name.casefold() == wanted:
                return folder.name
        raise ValueError(f"IMAP folder does not exist: {name}")

    def resolve_special_folder(self, flag: str, fallbacks: tuple[str, ...]) -> str:
        folders = self.list_folders()
        wanted_flag = flag.casefold()
        for folder in folders:
            if wanted_flag in folder.flags:
                return folder.name
        by_name = {folder.name.casefold(): folder.name for folder in folders}
        for candidate in fallbacks:
            if candidate.casefold() in by_name:
                return by_name[candidate.casefold()]
        raise RuntimeError(f"Server exposes no safe {flag} folder")

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
        limit = max(1, min(limit, 1000))
        with self._login() as client:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            criterion = f"UID {max(1, last_uid + 1)}:*"
            status, data = client.uid("search", None, criterion)
            if status != "OK" or not data or not data[0]:
                return []
            return [int(item) for item in data[0].split()][:limit]

    def fetch_uid_rfc822(self, uid: int, folder: str = "INBOX") -> tuple[bytes, bool]:
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

    def mark_seen(self, uid: int, folder: str = "INBOX") -> None:
        with self._login() as client:
            status, _ = client.select(folder, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            status, _ = client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Seen)")
            if status != "OK":
                raise RuntimeError(f"Unable to mark IMAP UID {uid} as seen")

    def mark_unseen(self, uid: int, folder: str = "INBOX") -> None:
        with self._login() as client:
            status, _ = client.select(folder, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            status, _ = client.uid("store", str(uid), "-FLAGS.SILENT", "(\\Seen)")
            if status != "OK":
                raise RuntimeError(f"Unable to mark IMAP UID {uid} as unseen")

    def move_uid(self, uid: int, destination: str, folder: str = "INBOX") -> None:
        destination = self.resolve_folder(destination)
        with self._login() as client:
            status, _ = client.select(folder, readonly=False)
            if status != "OK":
                raise RuntimeError(f"Unable to select IMAP folder {folder!r}")
            status, _ = client.uid("copy", str(uid), self._quote_mailbox(destination))
            if status != "OK":
                raise RuntimeError(f"Unable to copy IMAP UID {uid} to {destination!r}")
            status, _ = client.uid("store", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
            if status != "OK":
                raise RuntimeError(f"Unable to flag source IMAP UID {uid} for deletion")
            client.expunge()

    def archive_uid(self, uid: int, folder: str = "INBOX") -> str:
        destination = self.resolve_special_folder(
            "\\archive",
            ("Archive", "Archiv", "Archives", "[Gmail]/All Mail", "[Google Mail]/All Mail"),
        )
        self.move_uid(uid, destination, folder)
        return destination

    def trash_uid(self, uid: int, folder: str = "INBOX") -> str:
        destination = self.resolve_special_folder(
            "\\trash",
            ("Trash", "Papierkorb", "Deleted Items", "Deleted Messages", "[Gmail]/Trash", "[Google Mail]/Trash"),
        )
        self.move_uid(uid, destination, folder)
        return destination


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