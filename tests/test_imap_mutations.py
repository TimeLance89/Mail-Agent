from mail_agent_imap import ImapMailbox, MailboxConfig
from mail_agent_imap.client import ImapFolder


def mailbox():
    return ImapMailbox(
        MailboxConfig(
            email_address="owner@example.test",
            username="owner@example.test",
            password="secret",
            imap_host="imap.example.test",
        )
    )


def test_parse_special_use_folder():
    folder = mailbox()._parse_folder(b'(\\HasNoChildren \\Trash) "/" "Deleted Items"')
    assert folder is not None
    assert folder.name == "Deleted Items"
    assert "\\trash" in folder.flags


def test_special_folder_prefers_server_flag(monkeypatch):
    client = mailbox()
    monkeypatch.setattr(
        client,
        "list_folders",
        lambda: [
            ImapFolder("Archive", frozenset()),
            ImapFolder("Bin", frozenset({"\\trash"})),
        ],
    )
    assert client.resolve_special_folder("\\trash", ("Trash",)) == "Bin"


def test_missing_trash_folder_fails_instead_of_permanent_delete(monkeypatch):
    client = mailbox()
    monkeypatch.setattr(
        client,
        "list_folders",
        lambda: [ImapFolder("INBOX", frozenset()), ImapFolder("Archive", frozenset())],
    )
    try:
        client.resolve_special_folder("\\trash", ("Trash", "Papierkorb"))
    except RuntimeError as exc:
        assert "safe" in str(exc).lower()
    else:
        raise AssertionError("missing trash folder did not fail safe")
