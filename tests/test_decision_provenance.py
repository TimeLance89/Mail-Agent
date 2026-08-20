from mail_agent_core.models import MailActionProposal
from mail_agent_gateway.decision_provenance import normalize_decision_path


def _proposal(origin: str, **metadata):
    return MailActionProposal(
        action="classify",
        mailbox_id="mb",
        message_id="m1",
        confidence=0.98,
        reason="classified safely",
        category="newsletter",
        priority="low",
        metadata={"decision_origin": origin, **metadata},
    )


def _legacy_path():
    return [
        {"stage": "rule", "result": "normal", "detail": "owner rule checked"},
        {"stage": "llm", "result": "classify", "detail": "legacy label"},
        {"stage": "policy", "result": "allowed", "detail": "safe"},
    ]


def test_deterministic_skip_is_not_reported_as_llm():
    path = normalize_decision_path(
        _legacy_path(),
        _proposal(
            "deterministic",
            llm_called=False,
            decision_provenance=["header:bulk", "accepted_sender_pattern:newsletter"],
        ),
    )

    assert [item["stage"] for item in path] == ["rule", "pre_llm", "policy"]
    assert "header:bulk" in path[1]["detail"]
    assert "accepted_sender_pattern:newsletter" in path[1]["detail"]


def test_local_triage_and_full_llm_remain_distinguishable():
    local = normalize_decision_path(
        _legacy_path(),
        _proposal("local_triage", routed_provider="ollama", routed_model="small-local"),
    )
    full = normalize_decision_path(
        _legacy_path(),
        _proposal("llm", routed_provider="codex", routed_model="luna"),
    )

    assert local[1]["stage"] == "local_triage"
    assert "ollama / small-local" in local[1]["detail"]
    assert full[1]["stage"] == "llm"
    assert "codex / luna" in full[1]["detail"]


def test_normalization_never_changes_policy_or_artifact_stages():
    path = _legacy_path() + [{"stage": "artifact", "result": "no_action", "detail": "none"}]
    normalized = normalize_decision_path(path, _proposal("deterministic", llm_called=False))

    assert normalized[0] == path[0]
    assert normalized[2] == path[2]
    assert normalized[3] == path[3]
