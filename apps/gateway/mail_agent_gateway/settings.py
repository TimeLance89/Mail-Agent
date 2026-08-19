from __future__ import annotations

import os
from pathlib import Path

from .oauth_defaults import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, MICROSOFT_CLIENT_ID


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
    sync_interval_seconds = max(15, int(os.getenv("MAIL_AGENT_SYNC_INTERVAL_SECONDS", "60")))
    auto_sync_enabled = os.getenv("MAIL_AGENT_AUTO_SYNC", "true").lower() in {"1", "true", "yes", "on"}
    google_client_id = os.getenv("MAIL_AGENT_GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID).strip()
    google_client_secret = (
        os.getenv("MAIL_AGENT_GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET).strip() or None
    )
    google_redirect_uri = os.getenv(
        "MAIL_AGENT_GOOGLE_REDIRECT_URI",
        f"http://127.0.0.1:{port}",
    )
    microsoft_client_id = os.getenv(
        "MAIL_AGENT_MICROSOFT_CLIENT_ID",
        MICROSOFT_CLIENT_ID,
    ).strip()
    microsoft_tenant = os.getenv("MAIL_AGENT_MICROSOFT_TENANT", "common").strip() or "common"
    microsoft_redirect_uri = os.getenv(
        "MAIL_AGENT_MICROSOFT_REDIRECT_URI",
        f"http://localhost:{port}/v1/oauth/microsoft/callback",
    )
    update_feed_url = os.getenv(
        "MAIL_AGENT_UPDATE_FEED_URL",
        "https://api.github.com/repos/TimeLance89/Mail-Agent/releases/tags/preview-latest",
    )
    update_release_page = os.getenv(
        "MAIL_AGENT_UPDATE_RELEASE_PAGE",
        "https://github.com/TimeLance89/Mail-Agent/releases/tag/preview-latest",
    )


settings = Settings()
