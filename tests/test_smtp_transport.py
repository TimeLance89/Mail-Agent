from __future__ import annotations

from mail_agent_imap import MailboxConfig, SmtpSender
import mail_agent_imap.smtp as smtp_module


class FakeSMTP:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.calls = []

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def noop(self):
        self.calls.append("noop")

    def send_message(self, message):
        self.calls.append(("send", message["To"]))

    def close(self):
        self.calls.append("close")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.calls.append("exit")


def config(port: int) -> MailboxConfig:
    return MailboxConfig(
        email_address="user@example.com",
        username="user@example.com",
        password="secret",
        imap_host="imap.example.com",
        smtp_host="smtp.example.com",
        smtp_port=port,
    )


def test_port_465_uses_implicit_tls(monkeypatch):
    created = []

    def ssl_factory(host, port):
        smtp = FakeSMTP(host, port)
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtp_module.smtplib, "SMTP_SSL", ssl_factory)
    monkeypatch.setattr(smtp_module.smtplib, "SMTP", lambda *_: (_ for _ in ()).throw(AssertionError("STARTTLS transport must not be used")))

    SmtpSender(config(465)).test_connection()

    assert created[0].port == 465
    assert "starttls" not in created[0].calls
    assert ("login", "user@example.com", "secret") in created[0].calls


def test_port_587_requires_starttls_before_login(monkeypatch):
    created = []

    def starttls_factory(host, port):
        smtp = FakeSMTP(host, port)
        created.append(smtp)
        return smtp

    monkeypatch.setattr(smtp_module.smtplib, "SMTP", starttls_factory)
    monkeypatch.setattr(smtp_module.smtplib, "SMTP_SSL", lambda *_: (_ for _ in ()).throw(AssertionError("implicit TLS must not be used")))

    SmtpSender(config(587)).test_connection()

    assert created[0].port == 587
    assert created[0].calls[:3] == ["ehlo", "starttls", "ehlo"]
    assert ("login", "user@example.com", "secret") in created[0].calls
