from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


# 1) MailStore: retryable read reconciliation and attention-state lookup.
processed_unread = '''
    def list_processed_unread(self, mailbox_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return successfully processed messages still unread in the real mailbox mirror.

        This is intentionally separate from the LLM work queue: transient mailbox mutation failures
        can therefore be retried without analyzing the mail a second time.
        """
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT m.mailbox_id, m.uid, m.internet_message_id, m.thread_key, m.sender,
                       m.recipients_json, m.subject, m.sent_at, m.body_text, m.seen, m.synced_at,
                       m.remote_id, m.remote_thread_id, m.connector, m.agent_priority, m.agent_category,
                       m.agent_summary, m.needs_reply, m.analyzed_at
                  FROM messages AS m
                  JOIN agent_processing AS p
                    ON p.mailbox_id=m.mailbox_id
                   AND p.message_id=COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                 WHERE m.mailbox_id=? AND m.seen=0 AND p.status='processed'
                 ORDER BY p.processed_at ASC
                 LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def attention_is_resolved(self, mailbox_id: str, message_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM message_attention WHERE mailbox_id=? AND message_id=?",
                (mailbox_id, message_id),
            ).fetchone()
        return bool(row and row["status"] == "resolved")

'''
replace_once(
    "apps/gateway/mail_agent_gateway/mail_store.py",
    "\n\n    def list_attention(\n",
    "\n\n" + processed_unread + "    def list_attention(\n",
)

# 2) Runtime: central post-processing sweep; no LLM retry when mark-read fails.
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    "    MailHandlingAction,\n    RuleMode,",
    "    MailHandlingAction,\n    MailPriority,\n    RuleMode,",
)
helper = '''
    async def _reconcile_processed_read(
        self,
        mailbox_id: str,
        *,
        behavior: AgentBehaviorSettings,
        profile: AgentProfile,
        limit: int = 100,
    ) -> tuple[int, int]:
        if not behavior.mark_processed_read or self.action_executor is None:
            return 0, 0
        marked = 0
        errors = 0
        for item in self.mail_store.list_processed_unread(mailbox_id, limit=limit):
            message_id = str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid"))
            try:
                priority = MailPriority(str(item.get("agent_priority") or MailPriority.NORMAL.value))
            except ValueError:
                priority = MailPriority.NORMAL
            try:
                category = MailCategory(str(item.get("agent_category") or MailCategory.OTHER.value))
            except ValueError:
                category = MailCategory.OTHER
            rule_mode, _priority, _category = apply_rule_overrides(
                sender=str(item.get("sender") or ""),
                settings=behavior,
                priority=priority,
                category=category,
            )
            if rule_mode in {RuleMode.ANALYZE_ONLY, RuleMode.IGNORE}:
                continue
            proposal = MailActionProposal(
                action=MailActionType.MARK_READ,
                mailbox_id=mailbox_id,
                message_id=message_id,
                thread_id=str(item.get("thread_key") or "") or None,
                confidence=1.0,
                reason="Besitzer-Einstellung: erfolgreich bearbeitete Mail als gelesen markieren.",
            )
            policy = self.mail_agent.policy_engine.evaluate(profile, proposal)
            if not policy.allowed or policy.requires_approval:
                continue
            try:
                await self.action_executor.execute_direct(proposal)
                marked += 1
            except Exception as exc:
                errors += 1
                self.audit_log.append(
                    "agent_postprocess_mark_read_failed",
                    details={
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "error": str(exc),
                    },
                )
        return marked, errors

'''
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    "\n    async def run_mailbox(self, mailbox_id: str, *, force: bool = False) -> dict[str, Any]:\n",
    "\n" + helper + "    async def run_mailbox(self, mailbox_id: str, *, force: bool = False) -> dict[str, Any]:\n",
)
inline = '''                if (
                    behavior.mark_processed_read
                    and result.get("confidence_accepted")
                    and result.get("rule_mode") not in {RuleMode.ANALYZE_ONLY.value, RuleMode.IGNORE.value}
                    and self.action_executor is not None
                ):
                    source_after = self.mail_store.get_message(mailbox_id, context.message_id)
                    if source_after is not None and not source_after.get("seen"):
                        read_proposal = MailActionProposal(
                            action=MailActionType.MARK_READ,
                            mailbox_id=mailbox_id,
                            message_id=context.message_id,
                            thread_id=context.thread_id,
                            confidence=1.0,
                            reason="Besitzer-Einstellung: erfolgreich bearbeitete Mail als gelesen markieren.",
                        )
                        read_policy = self.mail_agent.policy_engine.evaluate(profile, read_proposal)
                        if read_policy.allowed and not read_policy.requires_approval:
                            try:
                                await self.action_executor.execute_direct(read_proposal)
                                marked_read += 1
                            except Exception as post_exc:
                                postprocess_errors += 1
                                self.audit_log.append(
                                    "agent_postprocess_mark_read_failed",
                                    details={
                                        "mailbox_id": mailbox_id,
                                        "message_id": context.message_id,
                                        "error": str(post_exc),
                                    },
                                )
'''
replace_once("apps/gateway/mail_agent_gateway/agent_runtime.py", inline, "")
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    "\n        pending_after = self.work_queue.pending_count(mailbox_id)\n",
    "\n        marked_read, postprocess_errors = await self._reconcile_processed_read(\n"
    "            mailbox_id, behavior=behavior, profile=profile, limit=100\n"
    "        )\n"
    "        pending_after = self.work_queue.pending_count(mailbox_id)\n",
)

# 3) System prompt distinguishes promotional advertising from recurring newsletters.
replace_once(
    "packages/agent_core/mail_agent_core/agent.py",
    "Always classify the current mail with one category and one priority, write a compact factual summary, and decide\nwhether the owner needs to reply. Do not mark routine marketing as urgent.",
    "Always classify the current mail with one category and one priority, write a compact factual summary, and decide\nwhether the owner needs to reply. Use category `advertising` for direct promotions, sales and commercial offers; use\ncategory `newsletter` for recurring editorial or informational bulk mail. Do not mark routine marketing as urgent.",
)

# 4) Attention API merges privacy-minimized Shadow results without mutating production intelligence.
old_route = '''@app.get("/v1/attention")
async def list_attention(mailbox_id: str | None = None, limit: int = 100) -> dict:
    _configuration_or_409()
    return {"attention": mail_store.list_attention(mailbox_id, limit)}
'''
new_route = '''@app.get("/v1/attention")
async def list_attention(mailbox_id: str | None = None, limit: int = 100) -> dict:
    _state, config = _configuration_or_409()
    limit = max(1, min(int(limit), 500))
    items = list(mail_store.list_attention(mailbox_id, limit))
    seen_keys = {
        (str(item.get("mailbox_id") or ""), str(item.get("remote_id") or item.get("internet_message_id") or item.get("uid") or ""))
        for item in items
    }
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    if behavior.execution_mode == AgentExecutionMode.SHADOW:
        reports = agent_runtime.shadow_reports.recent_reports(20, mailbox_id=mailbox_id)
        for report in reports:
            report_mailbox = str(report.get("mailbox_id") or "")
            for result in report.get("results", []) or []:
                message_id = str(result.get("message_id") or "")
                key = (report_mailbox, message_id)
                if not report_mailbox or not message_id or key in seen_keys:
                    continue
                priority = str(result.get("priority") or "normal")
                category = str(result.get("category") or "other")
                needs_reply = result.get("needs_reply") is True
                if not (needs_reply or priority in {"high", "urgent"} or category == "security"):
                    continue
                if mail_store.attention_is_resolved(report_mailbox, message_id):
                    seen_keys.add(key)
                    continue
                source = mail_store.get_message(report_mailbox, message_id)
                if source is None:
                    continue
                item = dict(source)
                item.update(
                    {
                        "agent_priority": priority,
                        "agent_category": category,
                        "agent_summary": str(result.get("reason") or "Shadow-Analyse: Aufmerksamkeit empfohlen."),
                        "needs_reply": needs_reply,
                        "analyzed_at": report.get("finished_at"),
                        "attention_status": "open",
                        "attention_source": "shadow",
                    }
                )
                items.append(item)
                seen_keys.add(key)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    items.sort(
        key=lambda item: (
            rank.get(str(item.get("agent_priority") or "normal"), 4),
            0 if item.get("needs_reply") is True else 1,
            str(item.get("analyzed_at") or item.get("sent_at") or ""),
        )
    )
    return {"attention": items[:limit]}
'''
replace_once("apps/gateway/mail_agent_gateway/main.py", old_route, new_route)

# 5) Desktop notification source is the same bundled attention feed; wording points to it.
replace_once(
    "apps/launcher/mail_agent_launcher/desktop_runtime.py",
    '"Eine neue dringende Nachricht wartet in deiner Inbox."',
    '"Eine neue dringende Nachricht wartet unter Handlungsbedarf."',
)
replace_once(
    "apps/launcher/mail_agent_launcher/desktop_runtime.py",
    'f"{count} neue wichtige Nachrichten warten in deiner Inbox."',
    'f"{count} neue wichtige Nachrichten warten unter Handlungsbedarf."',
)
replace_once(
    "apps/launcher/mail_agent_launcher/desktop_runtime.py",
    '"Eine neue wichtige Nachricht wartet in deiner Inbox."',
    '"Eine neue wichtige Nachricht wartet unter Handlungsbedarf."',
)
old_priority = '''    def _priority_messages(self) -> list[dict[str, Any]]:
        try:
            mailboxes = self.request("/v1/mailboxes").get("mailboxes", [])
        except Exception:
            return []
        messages: list[dict[str, Any]] = []
        for mailbox in list(mailboxes)[:10]:
            mailbox_id = str(mailbox.get("mailbox_id") or "")
            if not mailbox_id:
                continue
            try:
                payload = self.request(
                    f"/v1/mailboxes/{mailbox_id}/messages?limit=50"
                )
            except Exception:
                continue
            messages.extend(
                item for item in payload.get("messages", []) if isinstance(item, dict)
            )
        return messages
'''
new_priority = '''    def _priority_messages(self) -> list[dict[str, Any]]:
        try:
            return [
                item
                for item in self.request("/v1/attention?limit=100").get("attention", [])
                if isinstance(item, dict)
            ]
        except Exception:
            return []
'''
replace_once("apps/launcher/mail_agent_launcher/desktop_runtime.py", old_priority, new_priority)

# 6) UI indicates when an item comes from the side-effect-free Shadow analysis.
replace_once(
    "apps/web/attention-center.js",
    "      <div class=\"attention-tags\"><span>${escHtml(category)}</span>${item.needs_reply === true ? '<span>Antwort nötig</span>' : ''}</div>",
    "      <div class=\"attention-tags\"><span>${escHtml(category)}</span>${item.needs_reply === true ? '<span>Antwort nötig</span>' : ''}${item.attention_source === 'shadow' ? '<span>Shadow-Ergebnis</span>' : ''}</div>",
)

# 7) Contracts for retry reconciliation, Shadow attention and unified desktop feed.
write(
    "tests/test_mail_automation_contract.py",
    '''from __future__ import annotations

from pathlib import Path

from mail_agent_core.models import AgentBehaviorSettings, MailCategory, MailHandlingAction


ROOT = Path(__file__).resolve().parents[1]


def test_behavior_defaults_mark_successfully_processed_mail_read():
    behavior = AgentBehaviorSettings()
    assert behavior.mark_processed_read is True
    assert behavior.newsletter_action == MailHandlingAction.NONE
    assert behavior.advertising_action == MailHandlingAction.NONE
    assert MailCategory.ADVERTISING.value == "advertising"


def test_runtime_applies_category_handling_and_retryable_mark_read_postprocess():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    store = (ROOT / "apps/gateway/mail_agent_gateway/mail_store.py").read_text(encoding="utf-8")
    assert 'metadata["deterministic_category_handling"]' in source
    assert "behavior.newsletter_action" in source
    assert "behavior.advertising_action" in source
    assert "async def _reconcile_processed_read" in source
    assert "list_processed_unread" in source
    assert "agent_postprocess_mark_read_failed" in source
    assert "not policy.allowed or policy.requires_approval" in source
    assert "p.status='processed'" in store


def test_prompt_distinguishes_newsletter_and_advertising():
    source = (ROOT / "packages/agent_core/mail_agent_core/agent.py").read_text(encoding="utf-8")
    assert "category `advertising` for direct promotions" in source
    assert "category `newsletter` for recurring editorial" in source


def test_shadow_cycle_stays_remote_side_effect_free():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    shadow = source[source.index("async def _run_shadow_mailbox"):source.index("async def _reconcile_processed_read")]
    assert "execute_direct" not in shadow
''',
)

# Extend attention UI contract with Shadow merge.
path = ROOT / "tests/test_attention_ui_contract.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '    assert \'@app.post("/v1/attention/resolve")\' in main\n',
    '    assert \'@app.post("/v1/attention/resolve")\' in main\n'
    '    assert "shadow_reports.recent_reports" in main\n'
    '    assert "attention_source" in main\n'
    '    assert "Shadow-Ergebnis" in js\n',
    1,
)
path.write_text(text, encoding="utf-8")

# Update desktop snapshot test to use the canonical attention endpoint.
path = ROOT / "tests/test_desktop_runtime.py"
text = path.read_text(encoding="utf-8")
start = text.index("def test_gateway_snapshot_collects_recent_messages_for_desktop_priority_notifications")
replacement = '''def test_gateway_snapshot_collects_attention_feed_for_desktop_priority_notifications(monkeypatch):
    client = DesktopGatewayClient("http://127.0.0.1:8765")

    def fake_request(path, *, method="GET", payload=None):
        if path == "/v1/settings":
            return {"behavior": {"enabled": True, "execution_mode": "shadow"}}
        if path == "/v1/agent/brain":
            return {"pending_total": 0}
        if path.startswith("/v1/approvals"):
            return {"approvals": []}
        if path.startswith("/v1/drafts"):
            return {"drafts": []}
        if path == "/v1/system/health":
            return {"overall": "ok", "checks": []}
        if path == "/v1/attention?limit=100":
            return {"attention": [{"mailbox_id": "mb1", "remote_id": "m1", "agent_priority": "high", "attention_source": "shadow"}]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "request", fake_request)
    snapshot = client.snapshot()
    messages = snapshot["health"]["_desktop_priority_messages"]
    assert [item["remote_id"] for item in messages] == ["m1"]
    assert messages[0]["attention_source"] == "shadow"
'''
text = text[:start] + replacement + "\n"
path.write_text(text, encoding="utf-8")

# Dynamic store test: processed unread is separate from analysis queue.
path = ROOT / "tests/test_agent_queue_claims.py"
text = path.read_text(encoding="utf-8")
text += '''

def test_successfully_processed_unread_mail_is_available_for_postprocess_without_requeue(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1)])
    store.record_agent_processing("mb-1", "remote-1", status="processed")
    queue = AgentWorkQueue(store)

    assert queue.list_pending("mb-1", 1) == []
    unread = store.list_processed_unread("mb-1")
    assert [item["remote_id"] for item in unread] == ["remote-1"]
'''
path.write_text(text, encoding="utf-8")

# Self-clean staging infrastructure.
(ROOT / ".github/workflows/refine-0138.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
print("0.13.8 refinements applied")
