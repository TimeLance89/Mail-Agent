from email.message import EmailMessage

from mail_agent_gateway.sync import parse_message


def test_parse_message_extracts_local_mail_record_without_attachments():
    message = EmailMessage()
    message["From"] = "Alice <alice@example.com>"
    message["To"] = "Me <me@example.com>"
    message["Subject"] = "Re: Projekt"
    message["Message-ID"] = "<reply@example.com>"
    message["In-Reply-To"] = "<root@example.com>"
    message["Date"] = "Tue, 18 Aug 2026 12:00:00 +0200"
    message.set_content("Hallo Welt")
    message.add_attachment(b"secret bytes", maintype="application", subtype="octet-stream", filename="x.bin")

    stored = parse_message("mb_one", 7, message.as_bytes(), seen=False)
    assert stored.uid == 7
    assert stored.sender == "alice@example.com"
    assert stored.recipients == ["me@example.com"]
    assert stored.subject == "Re: Projekt"
    assert stored.body_text == "Hallo Welt"
    assert "secret bytes" not in stored.body_text
    assert stored.seen is False
