from __future__ import annotations

from typing import Any

from mail_agent_core.models import MailActionProposal


_ORIGIN_STAGE = {
    "deterministic": "pre_llm",
    "local_triage": "local_triage",
    "llm": "llm",
}


def normalize_decision_path(
    decision_path: list[dict[str, Any]] | None,
    proposal: MailActionProposal,
) -> list[dict[str, Any]]:
    """Make the explainability path reflect the route that actually produced the proposal.

    AgentRuntime predates the 0.16 pre-LLM layer and therefore names its reasoning slot `llm`.
    Adaptive proposals carry authoritative route metadata. This function rewrites only that
    explainability label/detail; policy, approval and execution decisions are never changed.
    """

    rows = [dict(item) for item in (decision_path or [])]
    metadata = dict(proposal.metadata or {})
    origin = str(metadata.get("decision_origin") or "llm")
    stage = _ORIGIN_STAGE.get(origin, "llm")
    provenance = [str(item) for item in metadata.get("decision_provenance") or [] if str(item)]

    if stage == "pre_llm":
        detail = proposal.reason or "Deterministische Pre-LLM-Entscheidung."
        if provenance:
            detail = f"{detail} Evidenz: {', '.join(provenance)}"
    elif stage == "local_triage":
        provider = str(metadata.get("routed_provider") or "lokales Modell")
        model = str(metadata.get("routed_model") or "")
        route = f"{provider} / {model}" if model else provider
        detail = proposal.reason or "Lokale Triage mit hoher Konfidenz."
        detail = f"{route}: {detail}"
    else:
        provider = str(metadata.get("routed_provider") or "LLM")
        model = str(metadata.get("routed_model") or "")
        route = f"{provider} / {model}" if model else provider
        detail = proposal.reason or proposal.summary or "LLM-Vorschlag erzeugt."
        detail = f"{route}: {detail}"

    replacement = {
        "stage": stage,
        "result": proposal.action.value,
        "detail": detail[:1600],
    }
    for index, item in enumerate(rows):
        if item.get("stage") == "llm":
            rows[index] = replacement
            break
    else:
        insert_at = 1 if rows and rows[0].get("stage") == "rule" else 0
        rows.insert(insert_at, replacement)
    return rows
