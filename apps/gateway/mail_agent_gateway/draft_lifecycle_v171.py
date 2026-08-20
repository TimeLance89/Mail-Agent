from __future__ import annotations

from typing import Any

from .mail_store import MailStore, utc_now


def install_active_draft_filter(store: MailStore) -> None:
    if getattr(store, "_v171_active_draft_filter", False):
        return
    original = store.list_drafts

    def list_active(mailbox_id: str | None = None, limit: int = 100):
        requested = max(1, min(int(limit), 500))
        items = original(mailbox_id, 500)
        return [item for item in items if item.get("status") != "discarded"][:requested]

    store.list_drafts = list_active  # type: ignore[method-assign]
    store._v171_active_draft_filter = True  # type: ignore[attr-defined]


def discard_draft(
    store: MailStore,
    audit_log: Any,
    draft_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    now = utc_now()
    rejected_pending = False
    approval_id: str | None = None
    with store._lock, store._connect() as conn:  # noqa: SLF001 - local persistence boundary
        row = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        if row["status"] == "sent":
            raise RuntimeError("Ein bereits gesendeter Entwurf kann nicht verworfen werden")
        if row["status"] == "discarded":
            return store._draft_row(row)  # noqa: SLF001

        approval_id = row["approval_id"]
        if approval_id:
            approval = conn.execute(
                "SELECT status, execution_status FROM approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
            if approval is None:
                raise RuntimeError("Die verknüpfte Freigabe des Entwurfs fehlt")
            if approval["status"] == "pending":
                conn.execute(
                    """
                    UPDATE approvals
                       SET status='rejected', decided_at=?, decided_by=?, execution_status='not_applicable'
                     WHERE approval_id=? AND status='pending'
                    """,
                    (now, actor, approval_id),
                )
                rejected_pending = True
            elif approval["status"] != "rejected":
                raise RuntimeError(
                    "Die Freigabe wurde bereits erteilt. Prüfe zuerst den Ausführungsstatus, bevor der Entwurf verworfen wird."
                )

        conn.execute(
            """
            UPDATE drafts
               SET status='discarded', updated_at=?, edited_by=?
             WHERE draft_id=?
            """,
            (now, actor, draft_id),
        )
        updated = conn.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()

    audit_log.append(
        "draft_discarded",
        actor=actor,
        details={
            "draft_id": draft_id,
            "approval_id": approval_id,
            "pending_approval_rejected": rejected_pending,
        },
    )
    return store._draft_row(updated)  # noqa: SLF001
