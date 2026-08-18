from pathlib import Path

from mail_agent_gateway.audit import AuditLog


def test_audit_log_appends_and_limits(tmp_path: Path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append("one", details={"value": 1})
    audit.append("two", details={"value": 2})
    events = audit.read_recent(1)
    assert len(events) == 1
    assert events[0]["event_type"] == "two"
    assert events[0]["details"]["value"] == 2
