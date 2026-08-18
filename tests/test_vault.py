from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from mail_agent_gateway.vault import CredentialVault


def test_vault_encrypts_secret_at_rest(tmp_path: Path):
    vault = CredentialVault(tmp_path / "secrets.vault", tmp_path / "vault.key")
    secret = "super-secret-app-password"
    vault.set_secret("mailbox:one:password", secret)

    assert vault.get_secret("mailbox:one:password") == secret
    assert secret not in (tmp_path / "secrets.vault").read_text(encoding="utf-8")
    assert (tmp_path / "vault.key").read_bytes() != secret.encode()


def test_vault_binds_ciphertext_to_reference(tmp_path: Path):
    vault = CredentialVault(tmp_path / "secrets.vault", tmp_path / "vault.key")
    vault.set_secret("mailbox:one:password", "alpha")

    data = __import__("json").loads((tmp_path / "secrets.vault").read_text())
    data["entries"]["mailbox:two:password"] = data["entries"]["mailbox:one:password"]
    (tmp_path / "secrets.vault").write_text(__import__("json").dumps(data))

    with pytest.raises(InvalidTag):
        vault.get_secret("mailbox:two:password")
