from __future__ import annotations

import re
from collections.abc import Callable

from .identity import AgentIdentity, IdentityManager
from .models import MailActionProposal, MailActionType

_BEGIN = "[MAIL-AGENT-IDENTITY]"
_END = "[/MAIL-AGENT-IDENTITY]"
_BLOCK = re.compile(
    rf"\n*--\n{re.escape(_BEGIN)}.*?{re.escape(_END)}\s*$",
    flags=re.DOTALL,
)
_SIGNATURE = re.compile(r"Agent-Signature: ed25519:([A-Za-z0-9+/=]+)")
_OUTBOUND = {
    MailActionType.CREATE_DRAFT,
    MailActionType.SEND_REPLY,
    MailActionType.FORWARD,
}


def _unsigned_content(body: str) -> str:
    return _BLOCK.sub("", body.rstrip()).rstrip()


def _signature_payload(content: str, identity: AgentIdentity) -> bytes:
    return (
        "MAIL-AGENT-MESSAGE-SIGNATURE-V1\n"
        f"agent_id={identity.agent_id}\n"
        f"fingerprint={identity.fingerprint}\n"
        "body=\n"
        f"{content}"
    ).encode("utf-8")


def mandatory_agent_footer(identity: AgentIdentity, cryptographic_signature: str) -> str:
    return (
        "--\n"
        f"{_BEGIN}\n"
        "Diese Nachricht wurde von einem E-Mail-Agenten bearbeitet.\n"
        f"MAIL-AGENT: {identity.agent_name}\n"
        f"Agent-ID: {identity.agent_id}\n"
        f"Agent-Fingerprint: {identity.fingerprint}\n"
        f"Agent-Signature: ed25519:{cryptographic_signature}\n"
        f"{_END}"
    )


def enforce_agent_signature(
    body: str,
    identity: AgentIdentity,
    *,
    sign_payload: Callable[[bytes], str],
    user_signature: str = "",
) -> tuple[str, str]:
    if not body or not body.strip():
        raise ValueError("Outgoing agent mail must contain a body")
    clean = _unsigned_content(body)
    if user_signature.strip() and not clean.endswith(user_signature.strip()):
        clean = f"{clean}\n\n{user_signature.strip()}"
    cryptographic_signature = sign_payload(_signature_payload(clean, identity))
    return (
        f"{clean}\n\n{mandatory_agent_footer(identity, cryptographic_signature)}",
        cryptographic_signature,
    )


def proposal_requires_agent_signature(proposal: MailActionProposal) -> bool:
    return proposal.action in _OUTBOUND


def stamp_outgoing_proposal(
    proposal: MailActionProposal,
    identity: AgentIdentity,
    *,
    sign_payload: Callable[[bytes], str],
    user_signature: str = "",
) -> MailActionProposal:
    if not proposal_requires_agent_signature(proposal):
        return proposal
    proposal.body, cryptographic_signature = enforce_agent_signature(
        proposal.body or "",
        identity,
        sign_payload=sign_payload,
        user_signature=user_signature,
    )
    metadata = dict(proposal.metadata)
    metadata.update(
        {
            "agent_generated": True,
            "agent_id": identity.agent_id,
            "agent_fingerprint": identity.fingerprint,
            "agent_message_signature": cryptographic_signature,
            "agent_signature_algorithm": "ed25519",
            "agent_signature_required": True,
        }
    )
    proposal.metadata = metadata
    return proposal


def assert_mandatory_agent_signature(body: str, identity: AgentIdentity) -> None:
    match = _SIGNATURE.search(body)
    required = (
        _BEGIN in body
        and _END in body
        and f"Agent-ID: {identity.agent_id}" in body
        and f"Agent-Fingerprint: {identity.fingerprint}" in body
        and match is not None
    )
    if not required:
        raise ValueError("Mandatory MAIL-AGENT identity signature is missing")
    content = _unsigned_content(body)
    if not IdentityManager.verify(
        public_key_b64=identity.public_key,
        payload=_signature_payload(content, identity),
        signature_b64=match.group(1),
    ):
        raise ValueError("Mandatory MAIL-AGENT identity signature is invalid")
