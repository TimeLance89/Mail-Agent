from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .client import MailboxConfig


class SmtpSender:
    """SMTP sender that selects the secure transport from the configured submission port.

    Port 465 uses implicit TLS (SMTPS). Other submission ports, especially 587, use
    STARTTLS before authentication. MAIL-AGENT never falls back to plaintext auth.
    """

    def __init__(self, config: MailboxConfig):
        self.config = config

    def _connect(self):
        if not self.config.smtp_host:
            raise ValueError("SMTP host is not configured")
        if int(self.config.smtp_port) == 465:
            return smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port)
        smtp = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)
        try:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            return smtp
        except Exception:
            smtp.close()
            raise

    def test_connection(self) -> None:
        with self._connect() as smtp:
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
        message = EmailMessage()
        message["From"] = self.config.email_address
        message["To"] = to
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
        if references:
            message["References"] = references
        message.set_content(body)
        with self._connect() as smtp:
            smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)
