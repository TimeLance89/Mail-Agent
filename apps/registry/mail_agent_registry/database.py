from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class RegistryDatabase:
    def __init__(self, path: str):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL UNIQUE,
                    agent_name TEXT NOT NULL,
                    usage_type TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def upsert_agent(self, values: dict[str, str]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO agents (
                    agent_id, owner_id, installation_id, agent_name, usage_type,
                    public_key, fingerprint, created_at, app_version, registered_at, last_seen_at
                ) VALUES (
                    :agent_id, :owner_id, :installation_id, :agent_name, :usage_type,
                    :public_key, :fingerprint, :created_at, :app_version, :registered_at, :last_seen_at
                )
                ON CONFLICT(agent_id) DO UPDATE SET
                    owner_id=excluded.owner_id,
                    agent_name=excluded.agent_name,
                    usage_type=excluded.usage_type,
                    public_key=excluded.public_key,
                    fingerprint=excluded.fingerprint,
                    app_version=excluded.app_version,
                    last_seen_at=excluded.last_seen_at
                """,
                values,
            )

    def get_agent(self, agent_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return dict(row) if row else None


def default_database() -> RegistryDatabase:
    return RegistryDatabase(os.getenv("MAIL_AGENT_REGISTRY_DB", "./runtime/registry/registry.db"))
