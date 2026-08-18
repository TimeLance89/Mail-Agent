from pathlib import Path

from mail_agent_core.identity import IdentityManager


def test_identity_round_trip_and_signature(tmp_path: Path):
    manager = IdentityManager(tmp_path)
    identity = manager.create(owner_id="owner-1", agent_name="Nova", usage_type="private")

    assert manager.exists()
    assert manager.load() == identity

    payload = b"mail-agent-proof"
    signature = manager.sign(payload)
    assert IdentityManager.verify(
        public_key_b64=identity.public_key,
        payload=payload,
        signature_b64=signature,
    )
    assert not IdentityManager.verify(
        public_key_b64=identity.public_key,
        payload=b"tampered",
        signature_b64=signature,
    )
