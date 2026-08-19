from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from mail_agent_core.identity import IdentityManager

from .agent_queue import AgentWorkQueue
from .mail_store import MailStore, utc_now
from .state import JsonStateStore
from .vault import CredentialVault

_OUTBOUND_ACTIONS = {"send_reply", "forward"}


class RecoveryManager:
    """Local diagnostics and conservative crash recovery.

    Outbound execution is special: if the process dies after the remote provider accepted a send
    but before SQLite records success, replaying automatically could duplicate mail. Stale outbound
    executions therefore become `uncertain` and require an explicit owner reconciliation.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        mail_store: MailStore,
        identity_manager: IdentityManager,
        state_store: JsonStateStore,
        vault: CredentialVault,
        providers: dict[str, Any],
        mailbox_supplier: Callable[[], list[dict]],
    ) -> None:
        self.data_dir = data_dir
        self.mail_store = mail_store
        self.identity_manager = identity_manager
        self.state_store = state_store
        self.vault = vault
        self.providers = providers
        self.mailbox_supplier = mailbox_supplier
        self.live_queue = AgentWorkQueue(mail_store)
        self.shadow_queue = AgentWorkQueue(mail_store, processing_table="agent_shadow_processing")

    def recover_stale_executions(self, *, max_age_seconds: int = 0) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(seconds=max(0, max_age_seconds))).isoformat()
        outbound_uncertain = 0
        retryable_failed = 0
        with self.mail_store._lock, self.mail_store._connect() as conn:
            rows = conn.execute(
                """
                SELECT approval_id, action
                FROM approvals
                WHERE status='approved'
                  AND execution_status='executing'
                  AND execution_started_at IS NOT NULL
                  AND execution_started_at < ?
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                approval_id = str(row["approval_id"])
                action = str(row["action"])
                if action in _OUTBOUND_ACTIONS:
                    conn.execute(
                        """
                        UPDATE approvals
                        SET execution_status='uncertain',
                            execution_error=?
                        WHERE approval_id=? AND execution_status='executing'
                        """,
                        (
                            "MAIL-AGENT wurde während des Versands beendet. Vor einem erneuten "
                            "Versuch muss im Gesendet-Ordner geprüft werden, ob die Nachricht "
                            "bereits versendet wurde.",
                            approval_id,
                        ),
                    )
                    outbound_uncertain += 1
                else:
                    conn.execute(
                        """
                        UPDATE approvals
                        SET execution_status='failed',
                            execution_error=?
                        WHERE approval_id=? AND execution_status='executing'
                        """,
                        (
                            "Die Ausführung wurde durch einen vorherigen Programmabbruch "
                            "unterbrochen und kann erneut versucht werden.",
                            approval_id,
                        ),
                    )
                    retryable_failed += 1
        return {
            "outbound_uncertain": outbound_uncertain,
            "retryable_failed": retryable_failed,
        }

    def reconcile_uncertain(self, approval_id: str, *, outcome: str) -> dict[str, Any]:
        if outcome not in {"already_sent", "retry"}:
            raise ValueError("Unsupported reconciliation outcome")
        with self.mail_store._lock, self.mail_store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise KeyError(approval_id)
            if row["status"] != "approved" or row["execution_status"] != "uncertain":
                raise RuntimeError("Approval is not awaiting outbound reconciliation")
            if str(row["action"]) not in _OUTBOUND_ACTIONS:
                raise RuntimeError("Only uncertain outbound actions can be reconciled here")

            if outcome == "already_sent":
                conn.execute(
                    """
                    UPDATE approvals
                    SET execution_status='sent', executed_at=?, execution_error=NULL,
                        execution_result_json=COALESCE(execution_result_json, '{}')
                    WHERE approval_id=? AND execution_status='uncertain'
                    """,
                    (utc_now(), approval_id),
                )
                conn.execute(
                    """
                    UPDATE drafts SET status='sent', updated_at=?
                    WHERE approval_id=?
                    """,
                    (utc_now(), approval_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE approvals
                    SET execution_status='ready', execution_started_at=NULL,
                        execution_error=NULL
                    WHERE approval_id=? AND execution_status='uncertain'
                    """,
                    (approval_id,),
                )
        return self.mail_store.get_approval(approval_id)

    async def report(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        checks.append(self._storage_check())
        checks.append(self._database_check())
        checks.append(self._identity_check())
        checks.extend(self._mailbox_checks())
        checks.append(await self._provider_check())
        checks.append(self._execution_check())
        checks.append(self._queue_check())

        rank = {"ok": 0, "warning": 1, "error": 2}
        worst = max((rank.get(str(item.get("status")), 0) for item in checks), default=0)
        overall = "ok" if worst == 0 else "degraded" if worst == 1 else "action_required"
        return {
            "overall": overall,
            "checked_at": utc_now(),
            "checks": checks,
            "summary": {
                "ok": sum(item.get("status") == "ok" for item in checks),
                "warning": sum(item.get("status") == "warning" for item in checks),
                "error": sum(item.get("status") == "error" for item in checks),
            },
        }

    def _storage_check(self) -> dict[str, Any]:
        probe = self.data_dir / ".mail-agent-write-probe"
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return self._check("storage", "ok", "Lokaler Datenspeicher ist schreibbar.")
        except Exception as exc:
            probe.unlink(missing_ok=True)
            return self._check(
                "storage",
                "error",
                f"Lokaler Datenspeicher ist nicht schreibbar: {exc}",
                action="open_logs",
            )

    def _database_check(self) -> dict[str, Any]:
        try:
            with self.mail_store._lock, self.mail_store._connect() as conn:
                result = str(conn.execute("PRAGMA quick_check").fetchone()[0])
            if result.lower() == "ok":
                return self._check("database", "ok", "SQLite-Integritätsprüfung erfolgreich.")
            return self._check(
                "database",
                "error",
                f"SQLite meldet ein Integritätsproblem: {result}",
                action="open_logs",
            )
        except Exception as exc:
            return self._check(
                "database",
                "error",
                f"SQLite konnte nicht geprüft werden: {exc}",
                action="open_logs",
            )

    def _identity_check(self) -> dict[str, Any]:
        if not self.identity_manager.exists():
            return self._check(
                "identity",
                "error",
                "Agentenidentität fehlt.",
                action="restart_onboarding",
            )
        try:
            identity = self.identity_manager.load()
            if not identity.agent_id or not identity.fingerprint:
                raise RuntimeError("Agent-ID oder Fingerprint fehlt")
            return self._check(
                "identity",
                "ok",
                f"Agent-ID vorhanden · {identity.fingerprint[:12]}…",
            )
        except Exception as exc:
            return self._check(
                "identity",
                "error",
                f"Agentenidentität kann nicht geladen werden: {exc}",
                action="open_logs",
            )

    def _mailbox_checks(self) -> list[dict[str, Any]]:
        mailboxes = self.mailbox_supplier()
        if not mailboxes:
            return [
                self._check(
                    "mailbox",
                    "warning",
                    "Noch kein Postfach verbunden.",
                    action="open_mailbox_setup",
                )
            ]
        checks: list[dict[str, Any]] = []
        for mailbox in mailboxes:
            mailbox_id = str(mailbox.get("mailbox_id") or "")
            address = str(mailbox.get("email_address") or mailbox_id)
            credential_ref = str(mailbox.get("credential_ref") or "")
            if not credential_ref or not self.vault.contains(credential_ref):
                checks.append(
                    self._check(
                        f"mailbox:{mailbox_id}",
                        "error",
                        f"{address}: Zugangsdaten/OAuth-Token fehlen im lokalen Vault.",
                        action="reconnect_mailbox",
                        mailbox_id=mailbox_id,
                    )
                )
                continue
            sync = self.mail_store.sync_status(mailbox_id)
            if sync.get("last_error"):
                checks.append(
                    self._check(
                        f"mailbox:{mailbox_id}",
                        "warning",
                        f"{address}: letzter Sync fehlgeschlagen · {sync['last_error']}",
                        action="retry_sync",
                        mailbox_id=mailbox_id,
                    )
                )
            else:
                checks.append(
                    self._check(
                        f"mailbox:{mailbox_id}",
                        "ok",
                        f"{address}: Vault und Sync-Zustand sind bereit.",
                        mailbox_id=mailbox_id,
                    )
                )
        return checks

    async def _provider_check(self) -> dict[str, Any]:
        state = self.state_store.read()
        config = state.get("configuration") if isinstance(state, dict) else None
        if not isinstance(config, dict):
            return self._check(
                "provider",
                "warning",
                "LLM ist noch nicht vollständig konfiguriert.",
                action="open_llm_settings",
            )
        name = str(config.get("provider") or "")
        provider = self.providers.get(name)
        if provider is None:
            return self._check(
                "provider",
                "error",
                f"Konfigurierter LLM-Provider {name!r} ist nicht verfügbar.",
                action="open_llm_settings",
            )
        try:
            health = await asyncio.wait_for(provider.health(), timeout=7.0)
        except Exception as exc:
            return self._check(
                "provider",
                "error",
                f"{name}: Provider-Prüfung fehlgeschlagen · {exc}",
                action="open_llm_settings",
            )
        return self._check(
            "provider",
            "ok" if health.available else "error",
            f"{name}: {health.detail}",
            action=None if health.available else "open_llm_settings",
        )

    def _execution_check(self) -> dict[str, Any]:
        with self.mail_store._lock, self.mail_store._connect() as conn:
            uncertain = int(
                conn.execute(
                    "SELECT COUNT(*) FROM approvals WHERE execution_status='uncertain'"
                ).fetchone()[0]
            )
            failed = int(
                conn.execute(
                    "SELECT COUNT(*) FROM approvals WHERE execution_status='failed'"
                ).fetchone()[0]
            )
            executing = int(
                conn.execute(
                    "SELECT COUNT(*) FROM approvals WHERE execution_status='executing'"
                ).fetchone()[0]
            )
        if uncertain:
            return self._check(
                "execution",
                "error",
                f"{uncertain} ausgehende Aktion(en) haben nach einem Abbruch einen unklaren Versandstatus.",
                action="review_uncertain",
                uncertain=uncertain,
                failed=failed,
                executing=executing,
            )
        if failed or executing:
            return self._check(
                "execution",
                "warning",
                f"{failed} fehlgeschlagen · {executing} aktuell in Ausführung.",
                action="open_approvals" if failed else None,
                uncertain=uncertain,
                failed=failed,
                executing=executing,
            )
        return self._check(
            "execution",
            "ok",
            "Keine hängenden oder unklaren Mail-Aktionen.",
            uncertain=0,
            failed=0,
            executing=0,
        )

    def _queue_check(self) -> dict[str, Any]:
        live = 0
        shadow = 0
        for mailbox in self.mailbox_supplier():
            mailbox_id = str(mailbox.get("mailbox_id") or "")
            if mailbox_id:
                live += self.live_queue.pending_count(mailbox_id)
                shadow += self.shadow_queue.pending_count(mailbox_id)
        return self._check(
            "queue",
            "ok",
            f"Agentenqueue bereit · {live} live · {shadow} Shadow offen.",
            live_pending=live,
            shadow_pending=shadow,
        )

    @staticmethod
    def _check(
        check_id: str,
        status: str,
        detail: str,
        *,
        action: str | None = None,
        **data: Any,
    ) -> dict[str, Any]:
        return {
            "id": check_id,
            "status": status,
            "detail": detail,
            "action": action,
            "data": data,
        }
