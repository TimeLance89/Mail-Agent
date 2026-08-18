from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    user: str
    model: str
    json_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    detail: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def health(self) -> ProviderHealth: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> str: ...


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434"):
        self.base_url = base_url.rstrip("/")

    async def health(self) -> ProviderHealth:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return ProviderHealth(True, "Ollama reachable")
        except Exception as exc:
            return ProviderHealth(False, f"Ollama unavailable: {exc}")

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
        return sorted(model["name"] for model in data.get("models", []) if "name" in model)

    async def complete(self, request: CompletionRequest) -> str:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "stream": False,
        }
        if request.json_schema:
            payload["format"] = request.json_schema
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data.get("message", {}).get("content", ""))


class CodexCliProvider(LLMProvider):
    """Adapter for the official local Codex CLI authenticated by the user.

    MAIL-AGENT never reads ChatGPT browser cookies or stores a ChatGPT password. Authentication
    remains owned by the official Codex client.
    """

    name = "codex"

    def __init__(self, binary: str = "codex"):
        self.binary = binary

    async def health(self) -> ProviderHealth:
        path = shutil.which(self.binary)
        if not path:
            return ProviderHealth(False, "Codex CLI not found in PATH")
        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            detail = (stdout or stderr).decode(errors="replace").strip()
            return ProviderHealth(proc.returncode == 0, detail or "Codex CLI detected")
        except Exception as exc:
            return ProviderHealth(False, f"Codex check failed: {exc}")

    async def list_models(self) -> list[str]:
        # The official client owns the actual model availability and subscription limits.
        return ["default"]

    def start_chatgpt_login(self) -> str:
        path = shutil.which(self.binary)
        if not path:
            raise RuntimeError("Codex CLI ist nicht installiert")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            [path, "--login"],
            close_fds=True,
            creationflags=creationflags,
        )
        return "Offizieller ChatGPT-Login wurde im Codex-Client gestartet"

    async def complete(self, request: CompletionRequest) -> str:
        path = shutil.which(self.binary)
        if not path:
            raise RuntimeError("Codex CLI not installed")

        envelope = {
            "system": request.system,
            "task": request.user,
            "output_schema": request.json_schema,
            "constraints": [
                "Return only the requested result.",
                "Do not execute mailbox, filesystem, network, or shell actions.",
            ],
        }
        prompt = json.dumps(envelope, ensure_ascii=False)

        proc = await asyncio.create_subprocess_exec(
            path,
            "exec",
            "--skip-git-repo-check",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "Codex execution failed")
        return stdout.decode(errors="replace").strip()
