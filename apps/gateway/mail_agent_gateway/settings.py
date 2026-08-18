from __future__ import annotations

import os
from pathlib import Path


class Settings:
    host = os.getenv("MAIL_AGENT_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("MAIL_AGENT_GATEWAY_PORT", "8765"))
    registry_url = os.getenv("MAIL_AGENT_REGISTRY_URL", "http://127.0.0.1:8770").rstrip("/")
    data_dir = Path(os.getenv("MAIL_AGENT_DATA_DIR", "./runtime/gateway")).resolve()
    cors_origins = [
        item.strip()
        for item in os.getenv(
            "MAIL_AGENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if item.strip()
    ]
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    codex_binary = os.getenv("CODEX_BINARY", "codex")


settings = Settings()
