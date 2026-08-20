from mail_agent_gateway.calendar_mail_intent import detect_calendar_intent


def message(subject: str, body: str, *, needs_reply=False):
    return {
        "mailbox_id": "mb",
        "remote_id": "msg_1",
        "thread_key": "thread_1",
        "sender": "person@example.com",
        "subject": subject,
        "body_text": body,
        "sent_at": "2026-08-20T12:00:00+02:00",
        "needs_reply": needs_reply,
    }


def test_detects_availability_request_with_date_context():
    result = detect_calendar_intent(
        message("Termin abstimmen", "Wann passt dir Montag um 14:30 Uhr?", needs_reply=True)
    )
    assert result is not None
    assert result["intent"] == "availability"
    assert result["has_explicit_time"] is True
    assert result["has_date_context"] is True
    assert result["score"] >= 5


def test_detects_reschedule_and_cancellation_intents():
    reschedule = detect_calendar_intent(message("Meeting", "Können wir den Termin auf Freitag verschieben?"))
    cancellation = detect_calendar_intent(message("Termin", "Ich muss den Termin leider absagen."))
    assert reschedule is not None and reschedule["intent"] == "reschedule"
    assert cancellation is not None and cancellation["intent"] == "cancellation"


def test_normal_mail_does_not_become_calendar_side_effect_suggestion():
    result = detect_calendar_intent(message("Rechnung", "Danke, die Rechnung ist angekommen."))
    assert result is None
