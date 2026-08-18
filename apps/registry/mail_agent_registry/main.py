from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .database import default_database

app = FastAPI(title="MAIL-AGENT Registry", version="0.2.4")
database = default_database()


class AgentRegistration(BaseModel):
    owner_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    installation_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    usage_type: str
    public_key: str
    fingerprint: str
    created_at: str
    app_version: str
    proof: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mail-agent-registry", "version": "0.2.4"}


def _canonical_registration(body: AgentRegistration) -> bytes:
    payload = body.model_dump(exclude={"proof"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_self_proof(body: AgentRegistration) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(body.public_key))
        key.verify(base64.b64decode(body.proof), _canonical_registration(body))
        return True
    except Exception:
        return False


@app.post("/v1/agents/register")
async def register_agent(body: AgentRegistration) -> dict:
    if not _verify_self_proof(body):
        raise HTTPException(status_code=400, detail="Invalid agent identity proof")

    try:
        public_raw = base64.b64decode(body.public_key, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid public key encoding") from exc
    expected_fingerprint = hashlib.sha256(public_raw).hexdigest()
    if body.fingerprint != expected_fingerprint:
        raise HTTPException(status_code=400, detail="Public-key fingerprint mismatch")

    existing = database.get_agent(body.agent_id)
    if existing and (
        existing["public_key"] != body.public_key
        or existing["installation_id"] != body.installation_id
        or existing["owner_id"] != body.owner_id
    ):
        raise HTTPException(status_code=409, detail="Agent identity is already bound and cannot be replaced")

    now = datetime.now(UTC).isoformat()
    values = body.model_dump(exclude={"proof"})
    values["registered_at"] = existing["registered_at"] if existing else now
    values["last_seen_at"] = now
    database.upsert_agent(values)
    return {
        "registered": True,
        "agent_id": body.agent_id,
        "owner_id": body.owner_id,
        "fingerprint": body.fingerprint,
    }


@app.get("/v1/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    agent = database.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.pop("public_key", None)
    return agent
