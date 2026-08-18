import base64
import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def test_registration_rejects_invalid_proof(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_REGISTRY_DB", str(tmp_path / "registry.db"))
    import importlib
    import mail_agent_registry.main as registry_main

    importlib.reload(registry_main)
    client = TestClient(registry_main.app)

    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    payload = {
        "owner_id": "owner",
        "agent_id": "ma_test",
        "installation_id": "inst_test",
        "agent_name": "Nova",
        "usage_type": "private",
        "public_key": base64.b64encode(public_raw).decode(),
        "fingerprint": hashlib.sha256(public_raw).hexdigest(),
        "created_at": "2026-01-01T00:00:00+00:00",
        "app_version": "0.1.0",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["proof"] = base64.b64encode(private.sign(canonical)).decode()
    response = client.post("/v1/agents/register", json=payload)
    assert response.status_code == 200

    payload["proof"] = base64.b64encode(b"not-a-valid-signature").decode()
    response = client.post("/v1/agents/register", json=payload)
    assert response.status_code == 400


def _signed_payload(private, *, agent_id="ma_bound", installation_id="inst_original", owner_id="owner"):
    public_raw = private.public_key().public_bytes_raw()
    payload = {
        "owner_id": owner_id,
        "agent_id": agent_id,
        "installation_id": installation_id,
        "agent_name": "Nova",
        "usage_type": "private",
        "public_key": base64.b64encode(public_raw).decode(),
        "fingerprint": hashlib.sha256(public_raw).hexdigest(),
        "created_at": "2026-01-01T00:00:00+00:00",
        "app_version": "0.1.0",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["proof"] = base64.b64encode(private.sign(canonical)).decode()
    return payload


def test_registration_rejects_agent_takeover(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_REGISTRY_DB", str(tmp_path / "takeover.db"))
    import importlib
    import mail_agent_registry.main as registry_main

    importlib.reload(registry_main)
    client = TestClient(registry_main.app)
    original = _signed_payload(Ed25519PrivateKey.generate())
    assert client.post("/v1/agents/register", json=original).status_code == 200

    attacker = _signed_payload(Ed25519PrivateKey.generate())
    response = client.post("/v1/agents/register", json=attacker)
    assert response.status_code == 409


def test_registration_rejects_fake_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_AGENT_REGISTRY_DB", str(tmp_path / "fingerprint.db"))
    import importlib
    import mail_agent_registry.main as registry_main

    importlib.reload(registry_main)
    private = Ed25519PrivateKey.generate()
    payload = _signed_payload(private, agent_id="ma_fingerprint", installation_id="inst_fingerprint")
    payload["fingerprint"] = "0" * 64
    canonical = json.dumps({k:v for k,v in payload.items() if k != "proof"}, sort_keys=True, separators=(",", ":")).encode()
    payload["proof"] = base64.b64encode(private.sign(canonical)).decode()
    response = TestClient(registry_main.app).post("/v1/agents/register", json=payload)
    assert response.status_code == 400
