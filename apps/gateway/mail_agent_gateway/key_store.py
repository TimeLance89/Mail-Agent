from __future__ import annotations

import base64
import ctypes
import os
import platform
import shutil
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Protocol


class MasterKeyStore(Protocol):
    backend_name: str

    def get_or_create(self) -> bytes: ...


class FileMasterKeyStore:
    backend_name = "permission-restricted-file"

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_or_create(self) -> bytes:
        if self.path.exists():
            key = self.path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("Credential vault master key is invalid")
            return key
        key = os.urandom(32)
        self.path.write_bytes(key)
        _chmod_private(self.path)
        return key


class WindowsDpapiMasterKeyStore:
    backend_name = "windows-dpapi"

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def available(cls) -> bool:
        return platform.system() == "Windows" and hasattr(ctypes, "windll")

    @classmethod
    def _blob(cls, data: bytes) -> tuple["WindowsDpapiMasterKeyStore.DATA_BLOB", ctypes.Array]:
        buffer = ctypes.create_string_buffer(data)
        blob = cls.DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    @classmethod
    def _protect(cls, data: bytes) -> bytes:
        in_blob, _ = cls._blob(data)
        out_blob = cls.DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        # CRYPTPROTECT_UI_FORBIDDEN: bind to the current Windows user without UI prompts.
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "MAIL-AGENT vault key",
            None,
            None,
            None,
            0x1,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def _unprotect(cls, data: bytes) -> bytes:
        in_blob, _ = cls._blob(data)
        out_blob = cls.DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def set_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Vault key must be 32 bytes")
        self.path.write_bytes(self._protect(key))
        _chmod_private(self.path)

    def get_or_create(self) -> bytes:
        if not self.available():
            raise RuntimeError("Windows DPAPI is unavailable")
        if self.path.exists():
            key = self._unprotect(self.path.read_bytes())
            if len(key) != 32:
                raise RuntimeError("DPAPI-protected vault key is invalid")
            return key
        key = os.urandom(32)
        self.set_key(key)
        return key


class MacOSKeychainMasterKeyStore:
    backend_name = "macos-keychain"
    service = "MAIL-AGENT Vault"
    account = "master-key"

    @classmethod
    def available(cls) -> bool:
        return platform.system() == "Darwin" and shutil.which("security") is not None

    def _lookup(self) -> bytes | None:
        found = subprocess.run(
            ["security", "find-generic-password", "-s", self.service, "-a", self.account, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        if found.returncode != 0:
            return None
        key = base64.b64decode(found.stdout.strip(), validate=True)
        if len(key) != 32:
            raise RuntimeError("Keychain vault key is invalid")
        return key

    def set_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Vault key must be 32 bytes")
        encoded = base64.b64encode(key).decode("ascii")
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", self.service, "-a", self.account, "-w", encoded],
            check=True,
            capture_output=True,
            text=True,
        )

    def get_or_create(self) -> bytes:
        if not self.available():
            raise RuntimeError("macOS Keychain is unavailable")
        key = self._lookup()
        if key is not None:
            return key
        key = os.urandom(32)
        self.set_key(key)
        return key


class LinuxSecretServiceMasterKeyStore:
    backend_name = "linux-secret-service"

    @classmethod
    def available(cls) -> bool:
        return platform.system() == "Linux" and shutil.which("secret-tool") is not None

    def _lookup(self) -> bytes | None:
        found = subprocess.run(
            ["secret-tool", "lookup", "application", "mail-agent", "key", "vault-master"],
            capture_output=True,
            text=True,
            check=False,
        )
        if found.returncode != 0 or not found.stdout.strip():
            return None
        key = base64.b64decode(found.stdout.strip(), validate=True)
        if len(key) != 32:
            raise RuntimeError("Secret Service vault key is invalid")
        return key

    def set_key(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Vault key must be 32 bytes")
        encoded = base64.b64encode(key).decode("ascii")
        subprocess.run(
            [
                "secret-tool", "store", "--label=MAIL-AGENT Vault",
                "application", "mail-agent", "key", "vault-master",
            ],
            input=encoded,
            text=True,
            check=True,
            capture_output=True,
        )

    def get_or_create(self) -> bytes:
        if not self.available():
            raise RuntimeError("Secret Service is unavailable")
        key = self._lookup()
        if key is not None:
            return key
        key = os.urandom(32)
        self.set_key(key)
        return key


class MigratingMasterKeyStore:
    """Move a legacy plaintext file key into an OS-native store when available."""

    def __init__(self, native: MasterKeyStore, legacy_path: Path):
        self.native = native
        self.legacy_path = legacy_path
        self.backend_name = native.backend_name

    def get_or_create(self) -> bytes:
        if self.legacy_path.exists():
            legacy = self.legacy_path.read_bytes()
            if len(legacy) != 32:
                raise RuntimeError("Legacy vault master key is invalid")
            lookup = getattr(self.native, "_lookup", None)
            native_existing = lookup() if callable(lookup) else (
                self.native.get_or_create() if getattr(self.native, "path", Path()).exists() else None
            )
            if native_existing is None:
                setter = getattr(self.native, "set_key", None)
                if not callable(setter):
                    return legacy
                setter(legacy)
                self.legacy_path.unlink(missing_ok=True)
                return legacy
            if native_existing == legacy:
                self.legacy_path.unlink(missing_ok=True)
                return legacy
            # Never rotate an existing encrypted vault implicitly. A conflict keeps the legacy key
            # active until an explicit operator-controlled migration is performed.
            return legacy
        return self.native.get_or_create()


def create_master_key_store(data_dir: Path) -> MasterKeyStore:
    legacy = data_dir / "vault.key"
    if WindowsDpapiMasterKeyStore.available():
        return MigratingMasterKeyStore(WindowsDpapiMasterKeyStore(data_dir / "vault.key.dpapi"), legacy)
    if MacOSKeychainMasterKeyStore.available():
        return MigratingMasterKeyStore(MacOSKeychainMasterKeyStore(), legacy)
    if LinuxSecretServiceMasterKeyStore.available():
        return MigratingMasterKeyStore(LinuxSecretServiceMasterKeyStore(), legacy)
    return FileMasterKeyStore(legacy)


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
