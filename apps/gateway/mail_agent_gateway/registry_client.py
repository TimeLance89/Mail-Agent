from __future__ import annotations

from dataclasses import asdict

import httpx

from mail_agent_core.identity import AgentIdentity, IdentityManager


class RegistryClient:
    def __init__(self, base_url: str, identity_manager: IdentityManager):
        self.base_url = base_url.rstrip("/")
        self.identity_manager = identity_manager

    async def register(self, identity: AgentIdentity) -> dict:
        payload = asdict(identity)
        canonical = self._canonical_payload(payload)
        request = {**payload, "proof": self.identity_manager.sign(canonical)}
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(f"{self.base_url}/v1/agents/register", json=request)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _canonical_payload(payload: dict) -> bytes:
        import json

        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
