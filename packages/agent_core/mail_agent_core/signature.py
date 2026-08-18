from __future__ import annotations

import re

from .identity import AgentIdentity
from .models import MailActionProposal, MailActionType

_BEGIN = "[MAIL-AGENT-IDENTITY]"
_END = "[/MAIL-AGENT-IDENTITY]"
_BLOCK = re.compile(
    rf"\n*--\n{re.escape(_BEGIN)}.*?{re.escape(_END)}\s*$",
    flags=re.DOTALL,
)
_OUTBOUND = {
    MailActionType.CREATE_DRAFT,
    MailActionType.SEND_REPLY,
    MailActionType.FORWARD,
}


def mandatory_agent_footer(identity: AgentIdentity) -> str:
    return (
        "--\n"
        f"{_BEGIN}\n"
        "Diese Nachricht wurde von einem E-Mail-Agenten bearbeitet.\n"
        f"MAIL-AGENT: {identity.agent_name}\n"
        f"Agent-ID: {identity.agent_id}\n"
        f"Agent-Fingerprint: {identity.fingerprint}\n"
        f"{_END}"
    )


def enforce_agent_signature(
    body: str,
    identity: AgentIdentity,
    *,
    user_signature: str = "",
) -> str:
    if not body or not body.strip():
        raise ValueError("Outgoing agent mail must contain a body")
    clean = _BLOCK.sub("", body.rstrip()).rstrip()
    if user_signature.strip() and not clean.endswith(user_signature.strip()):
        clean = f"{clean}\n\n{user_signature.strip()}"
    return f"{clean}\n\n{mandatory_agent_footer(identity)}"


def proposal_requires_agent_signature(proposal: MailActionProposal) -> bool:
    return proposal.action in _OUTBOUND


def stamp_outgoing_proposal(
    proposal: MailActionProposal,
    identity: AgentIdentity,
    *,
    user_signature: str = "",
) -> MailActionProposal:
    if not proposal_requires_agent_signature(proposal):
        return proposal
    proposal.body = enforce_agent_signature(
        proposal.body or "",
        identity,
        user_signature=user_signature,
    )
    metadata = dict(proposal.metadata)
    metadata.update(
        {
            "agent_generated": True,
            "agent_id": identity.agent_id,
            "agent_fingerprint": identity.fingerprint,
            "agent_signature_required": True,
        }
    )
    proposal.metadata = metadata
    return proposal


def assert_mandatory_agent_signature(body: str, identity: AgentIdentity) -> None:
    required = (
        _BEGIN in body
        and _END in body
        and f"Agent-ID: {identity.agent_id}" in body
        and f"Agent-Fingerprint: {identity.fingerprint}" in body
    )
    if not required:
        raise ValueError("Mandatory MAIL-AGENT identity signature is missing")
