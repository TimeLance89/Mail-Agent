from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialVault:
    """Small local encrypted secret store.

    v0.2 deliberately keeps the master key in a separate permission-restricted file.
    This protects secrets from accidental DB/state disclosure; OS keychain integration is
    the next hardening layer for protection against full local account compromise.
    """

    VERSION = 1

    def __init__(self, vault_path: Path, key_path: Path):
        self.vault_path = vault_path
        self.key_path = key_path
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _master_key(self) -> bytes:
        if not self.key_path.exists():
            key = AESGCM.generate_key(bit_length=256)
            self.key_path.write_bytes(key)
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
            return key
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise RuntimeError("Credential vault master key is invalid")
        return key

    def _read(self) -> dict[str, Any]:
        if not self.vault_path.exists():
            return {"version": self.VERSION, "entries": {}}
        data = json.loads(self.vault_path.read_text(encoding="utf-8"))
        if data.get("version") != self.VERSION or not isinstance(data.get("entries"), dict):
            raise RuntimeError("Unsupported credential vault format")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.vault_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.vault_path)
        try:
            os.chmod(self.vault_path, 0o600)
        except OSError:
            pass

    def set_secret(self, reference: str, secret: str) -> None:
        if not reference or not secret:
            raise ValueError("Vault reference and secret are required")
        nonce = os.urandom(12)
        encrypted = AESGCM(self._master_key()).encrypt(
            nonce,
            secret.encode("utf-8"),
            reference.encode("utf-8"),
        )
        entry = {
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        }
        with self._lock:
            data = self._read()
            data["entries"][reference] = entry
            self._write(data)

    def get_secret(self, reference: str) -> str:
        with self._lock:
            data = self._read()
            entry = data["entries"].get(reference)
        if entry is None:
            raise KeyError(reference)
        nonce = base64.b64decode(entry["nonce"])
        ciphertext = base64.b64decode(entry["ciphertext"])
        plaintext = AESGCM(self._master_key()).decrypt(
            nonce,
            ciphertext,
            reference.encode("utf-8"),
        )
        return plaintext.decode("utf-8")

    def delete_secret(self, reference: str) -> bool:
        with self._lock:
            data = self._read()
            if reference not in data["entries"]:
                return False
            del data["entries"][reference]
            self._write(data)
        return True

    def contains(self, reference: str) -> bool:
        with self._lock:
            return reference in self._read()["entries"]
