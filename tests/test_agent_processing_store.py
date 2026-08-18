from pathlib import Path

from mail_agent_gateway.mail_store import MailStore


def test_agent_processing_is_persistent_and_deduplicated(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    assert not store.is_agent_processed("mb", "msg")
    store.record_agent_processing(
        "mb",
        "msg",
        status="error",
        error="temporary provider failure",
    )
    assert not store.is_agent_processed("mb", "msg")
    store.record_agent_processing(
        "mb",
        "msg",
        status="processed",
        proposal_action="create_draft",
        confidence=0.91,
    )
    assert store.is_agent_processed("mb", "msg")
