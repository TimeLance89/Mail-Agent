from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
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


def _hidden_process_creationflags(platform_name: str | None = None) -> int:
    """Return flags that keep internal CLI helpers invisible on Windows."""

    platform_name = platform_name or os.name
    if platform_name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


async def _terminate_process_tree(proc: Any) -> None:
    """Best-effort bounded termination for provider subprocesses."""

    if getattr(proc, "returncode", None) is not None:
        return

    pid = getattr(proc, "pid", None)
    terminated = False
    if os.name == "nt" and pid:
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
                creationflags=_hidden_process_creationflags(),
            )
            terminated = True
        except Exception:
            terminated = False

    if not terminated:
        try:
            proc.kill()
        except (ProcessLookupError, AttributeError):
            return
        except Exception:
            pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except Exception:
        pass


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

    def _command(self, *args: str, platform_name: str | None = None) -> list[str]:
        path = shutil.which(self.binary)
        if not path:
            raise RuntimeError("Codex CLI ist nicht installiert")
        platform_name = platform_name or os.name
        if platform_name == "nt" and Path(path).suffix.lower() in {".cmd", ".bat"}:
            command_line = subprocess.list2cmdline([path, *args])
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
        return [path, *args]

    async def health(self) -> ProviderHealth:
        try:
            command = self._command("--version")
        except RuntimeError as exc:
            return ProviderHealth(False, str(exc))
        proc: Any | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_hidden_process_creationflags(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            detail = (stdout or stderr).decode(errors="replace").strip()
            return ProviderHealth(proc.returncode == 0, detail or "Codex CLI detected")
        except TimeoutError:
            if proc is not None:
                await _terminate_process_tree(proc)
            return ProviderHealth(False, "Codex check timed out")
        except Exception as exc:
            if proc is not None:
                await _terminate_process_tree(proc)
            return ProviderHealth(False, f"Codex check failed: {exc}")

    @staticmethod
    def _models_from_catalog(payload: Any) -> list[str]:
        """Extract user-visible model slugs from Codex' JSON model catalog."""

        if isinstance(payload, dict):
            entries = payload.get("models", [])
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []

        models: list[str] = []
        for entry in entries:
            if isinstance(entry, str):
                slug = entry.strip()
                visibility = "list"
            elif isinstance(entry, dict):
                slug = str(
                    entry.get("slug") or entry.get("model") or entry.get("id") or ""
                ).strip()
                visibility = str(entry.get("visibility") or "list").strip().lower()
            else:
                continue
            if not slug or visibility in {"hide", "hidden", "internal"}:
                continue
            if slug not in models:
                models.append(slug)
        return models

    async def _debug_model_catalog(self, *, bundled: bool, timeout: float) -> list[str]:
        args = ["debug", "models"]
        if bundled:
            args.append("--bundled")
        command = self._command(*args)
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=_hidden_process_creationflags(),
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            await _terminate_process_tree(proc)
            return []
        except Exception:
            await _terminate_process_tree(proc)
            return []
        if proc.returncode != 0:
            return []
        try:
            return self._models_from_catalog(json.loads(stdout.decode(errors="replace")))
        except (json.JSONDecodeError, UnicodeError):
            return []

    async def list_models(self) -> list[str]:
        """Discover models from the user's installed official Codex client."""

        try:
            models = await self._debug_model_catalog(bundled=False, timeout=8.0)
            if models:
                return models
            return await self._debug_model_catalog(bundled=True, timeout=3.0)
        except (RuntimeError, OSError):
            return []

    def start_chatgpt_login(self) -> str:
        command = self._command("--login")
        subprocess.Popen(
            command,
            close_fds=True,
            creationflags=_hidden_process_creationflags(),
        )
        return "Offizieller ChatGPT-Login wurde im Codex-Client gestartet"

    async def complete(self, request: CompletionRequest) -> str:
        envelope = {
            "system": request.system,
            "task": request.user,
            "output_schema": request.json_schema,
            "constraints": [
                "Return only the requested result.",
                "Do not execute mailbox, filesystem, network, or shell actions.",
            ],
        }
        prompt = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        args = ["exec", "--skip-git-repo-check"]
        if request.model and request.model != "default":
            args.extend(["-m", request.model])

        # Codex officially supports `codex exec -` with the prompt on stdin. Keeping the full mail,
        # thread and brain context out of argv avoids Windows' command-line length limit (WinError
        # 206) and also prevents prompt contents from being exposed in process command-line tools.
        args.append("-")
        command = self._command(*args)

        proc: Any | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=_hidden_process_creationflags(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt), timeout=180.0)
        except TimeoutError as exc:
            if proc is not None:
                await _terminate_process_tree(proc)
            raise RuntimeError("Codex execution timed out") from exc
        except Exception:
            if proc is not None:
                await _terminate_process_tree(proc)
            raise

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "Codex execution failed")
        return stdout.decode(errors="replace").strip()
