from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class AgentIdentity:
    owner_id: str
    agent_id: str
    installation_id: str
    agent_name: str
    usage_type: str
    public_key: str
    fingerprint: str
    created_at: str
    app_version: str = "0.16.1"


class IdentityManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.private_key_path = self.data_dir / "agent-ed25519.pem"
        self.identity_path = self.data_dir / "agent-identity.json"

    def exists(self) -> bool:
        return self.private_key_path.exists() and self.identity_path.exists()

    def create(self, *, owner_id: str, agent_name: str, usage_type: str) -> AgentIdentity:
        if self.exists():
            raise RuntimeError("Agent identity already exists")

        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.private_key_path.write_bytes(private_pem)
        try:
            os.chmod(self.private_key_path, 0o600)
        except OSError:
            pass

        public_raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        public_b64 = base64.b64encode(public_raw).decode("ascii")
        fingerprint = hashlib.sha256(public_raw).hexdigest()
        installation_seed = f"{platform.node()}:{uuid.uuid4()}".encode()
        installation_id = "inst_" + hashlib.sha256(installation_seed).hexdigest()[:24]
        identity = AgentIdentity(
            owner_id=owner_id,
            agent_id="ma_" + uuid.uuid4().hex,
            installation_id=installation_id,
            agent_name=agent_name,
            usage_type=usage_type,
            public_key=public_b64,
            fingerprint=fingerprint,
            created_at=datetime.now(UTC).isoformat(),
        )
        self.identity_path.write_text(json.dumps(asdict(identity), indent=2), encoding="utf-8")
        return identity

    def load(self) -> AgentIdentity:
        if not self.exists():
            raise RuntimeError("Agent identity has not been created")
        return AgentIdentity(**json.loads(self.identity_path.read_text(encoding="utf-8")))

    def _load_private_key(self) -> Ed25519PrivateKey:
        key = serialization.load_pem_private_key(self.private_key_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError("Stored key is not Ed25519")
        return key

    def sign(self, payload: bytes) -> str:
        signature = self._load_private_key().sign(payload)
        return base64.b64encode(signature).decode("ascii")

    @staticmethod
    def verify(*, public_key_b64: str, payload: bytes, signature_b64: str) -> bool:
        try:
            public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
            public.verify(base64.b64decode(signature_b64), payload)
            return True
        except (ValueError, TypeError):
            return False
        except Exception:
            return False