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
