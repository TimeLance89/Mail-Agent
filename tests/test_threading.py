from mail_agent_gateway.cloud_sync import _gmail_message
from mail_agent_gateway.sync import parse_message


def test_original_and_reply_share_thread_key():
    original = parse_message(
        "mb",
        1,
        b"From: a@example.test\r\nTo: b@example.test\r\nSubject: Hello\r\nMessage-ID: <root@example.test>\r\n\r\nFirst",
        seen=False,
    )
    reply = parse_message(
        "mb",
        2,
        b"From: b@example.test\r\nTo: a@example.test\r\nSubject: Re: Hello\r\nMessage-ID: <reply@example.test>\r\nIn-Reply-To: <root@example.test>\r\nReferences: <root@example.test>\r\n\r\nSecond",
        seen=False,
    )
    assert original.thread_key == reply.thread_key


def test_gmail_thread_id_is_authoritative_even_without_reply_headers():
    first = _gmail_message(
        "mb",
        "gmail-1",
        {
            "threadId": "provider-thread",
            "labelIds": ["INBOX"],
            "raw_bytes": b"From: a@example.test\r\nTo: b@example.test\r\nSubject: Topic\r\nMessage-ID: <one@example.test>\r\n\r\nFirst",
        },
    )
    second = _gmail_message(
        "mb",
        "gmail-2",
        {
            "threadId": "provider-thread",
            "labelIds": ["INBOX", "UNREAD"],
            "raw_bytes": b"From: a@example.test\r\nTo: b@example.test\r\nSubject: Topic\r\nMessage-ID: <two@example.test>\r\n\r\nSecond",
        },
    )
    assert first.thread_key == second.thread_key
    assert first.remote_thread_id == "provider-thread"
    assert second.remote_thread_id == "provider-thread"
