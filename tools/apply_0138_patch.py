from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"Missing replacement anchor in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def regex_once(path: str, pattern: str, repl: str, *, flags: int = 0) -> None:
    text = read(path)
    text, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Expected one regex replacement in {path}: {pattern!r}, got {count}")
    write(path, text)


# ---------------------------------------------------------------------------
# Version 0.13.8
# ---------------------------------------------------------------------------
regex_once("pyproject.toml", r'^version = "[^"]+"$', 'version = "0.13.8"', flags=re.MULTILINE)
regex_once(
    "packages/agent_core/mail_agent_core/identity.py",
    r'app_version: str = "[^"]+"',
    'app_version: str = "0.13.8"',
)
regex_once(
    "packaging/windows/MailAgent.iss",
    r'#define MyAppVersion "[^"]+"',
    '#define MyAppVersion "0.13.8"',
)
regex_once(
    "apps/web/desktop-links.js",
    r"const APP_VERSION = '[^']+';",
    "const APP_VERSION = '0.13.8';",
)

for path in (
    "tests/test_recovery_contract.py",
    "tests/test_startup_nonblocking.py",
    "tests/test_windows_update_restart.py",
):
    text = read(path)
    text = re.sub(r"0\.13\.\d+", "0.13.8", text)
    write(path, text)

# ---------------------------------------------------------------------------
# Behavior model: separate newsletter/advertising handling + processed-read.
# ---------------------------------------------------------------------------
replace_once(
    "packages/agent_core/mail_agent_core/models.py",
    '    NEWSLETTER = "newsletter"\n    NOTIFICATION = "notification"',
    '    NEWSLETTER = "newsletter"\n    ADVERTISING = "advertising"\n    NOTIFICATION = "notification"',
)
replace_once(
    "packages/agent_core/mail_agent_core/models.py",
    '\n\nclass RuleMode(StrEnum):\n',
    '\n\nclass MailHandlingAction(StrEnum):\n'
    '    NONE = "none"\n'
    '    MARK_READ = "mark_read"\n'
    '    ARCHIVE = "archive"\n'
    '\n\nclass RuleMode(StrEnum):\n',
)
replace_once(
    "packages/agent_core/mail_agent_core/models.py",
    '    auto_archive_low_priority: bool = False\n    minimum_confidence:',
    '    auto_archive_low_priority: bool = False\n'
    '    mark_processed_read: bool = True\n'
    '    newsletter_action: MailHandlingAction = MailHandlingAction.NONE\n'
    '    advertising_action: MailHandlingAction = MailHandlingAction.NONE\n'
    '    minimum_confidence:',
)

# ---------------------------------------------------------------------------
# Atomic queue claims. A message is durable `running` before the LLM starts.
# ---------------------------------------------------------------------------
write(
    "apps/gateway/mail_agent_gateway/agent_queue.py",
    '''from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .mail_store import MailStore

_ALLOWED_PROCESSING_TABLES = {"agent_processing", "agent_shadow_processing"}
_STALE_CLAIM_MINUTES = 15


class AgentWorkQueue:
    """Durable work queue with atomic claim-before-analysis semantics.

    Live and Shadow processing use separate durable processing tables. `list_pending` atomically
    moves selected rows to `running` before returning them. Overlapping sync/manual cycles therefore
    cannot send the same message to the LLM twice. Abandoned claims are retried after a conservative
    stale window, which is safely above the provider timeout.
    """

    def __init__(self, mail_store: MailStore, *, processing_table: str = "agent_processing"):
        if processing_table not in _ALLOWED_PROCESSING_TABLES:
            raise ValueError("Unsupported agent processing table")
        self.mail_store = mail_store
        self.processing_table = processing_table

    @staticmethod
    def _message_id(item: Any) -> str:
        return str(item["remote_id"] or item["internet_message_id"] or item["uid"])

    def list_pending(self, mailbox_id: str, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        table = self.processing_table
        now = datetime.now(UTC)
        stale_before = (now - timedelta(minutes=_STALE_CLAIM_MINUTES)).isoformat()
        now_text = now.isoformat()

        with self.mail_store._lock, self.mail_store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"""
                UPDATE {table}
                   SET status='error', error='Recovered stale running claim', processed_at=?
                 WHERE mailbox_id=? AND status='running' AND processed_at<?
                """,
                (now_text, mailbox_id, stale_before),
            )
            rows = conn.execute(
                f"""
                SELECT m.mailbox_id, m.uid, m.internet_message_id, m.thread_key, m.sender,
                       m.recipients_json, m.subject, m.sent_at, m.body_text, m.seen, m.synced_at,
                       m.remote_id, m.remote_thread_id, m.connector, m.agent_priority, m.agent_category,
                       m.agent_summary, m.needs_reply, m.analyzed_at
                FROM messages AS m
                LEFT JOIN {table} AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                ORDER BY CASE WHEN p.status IS NULL THEN 0 ELSE 1 END ASC, m.uid DESC
                LIMIT ?
                """,
                (mailbox_id, limit),
            ).fetchall()
            for row in rows:
                message_id = self._message_id(row)
                conn.execute(
                    f"""
                    INSERT INTO {table} (
                        mailbox_id, message_id, status, proposal_action, confidence, processed_at, error
                    ) VALUES (?, ?, 'running', NULL, NULL, ?, NULL)
                    ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                        status='running', proposal_action=NULL, confidence=NULL,
                        processed_at=excluded.processed_at, error=NULL
                    """,
                    (mailbox_id, message_id, now_text),
                )
            conn.commit()
        return [self.mail_store._message_row(row) for row in rows]

    def pending_count(self, mailbox_id: str) -> int:
        table = self.processing_table
        with self.mail_store._lock, self.mail_store._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM messages AS m
                LEFT JOIN {table} AS p
                  ON p.mailbox_id = m.mailbox_id
                 AND p.message_id = COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                WHERE m.mailbox_id=?
                  AND (p.status IS NULL OR p.status='error')
                """,
                (mailbox_id,),
            ).fetchone()
        return int(row["count"] if row else 0)
''',
)

# ---------------------------------------------------------------------------
# Attention persistence (privacy-local owner note, not audit payload).
# ---------------------------------------------------------------------------
replace_once(
    "apps/gateway/mail_agent_gateway/mail_store.py",
    """                CREATE INDEX IF NOT EXISTS idx_agent_shadow_processing_time
                    ON agent_shadow_processing(mailbox_id, processed_at DESC);
""",
    """                CREATE INDEX IF NOT EXISTS idx_agent_shadow_processing_time
                    ON agent_shadow_processing(mailbox_id, processed_at DESC);

                CREATE TABLE IF NOT EXISTS message_attention (
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    owner_note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (mailbox_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_message_attention_status
                    ON message_attention(status, updated_at DESC);
""",
)
attention_methods = '''
    def list_attention(
        self,
        mailbox_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        where_mailbox = "AND m.mailbox_id=?" if mailbox_id else ""
        params: list[Any] = [mailbox_id] if mailbox_id else []
        params.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.mailbox_id, m.uid, m.internet_message_id, m.thread_key, m.sender,
                       m.recipients_json, m.subject, m.sent_at, m.body_text, m.seen, m.synced_at,
                       m.remote_id, m.remote_thread_id, m.connector, m.agent_priority, m.agent_category,
                       m.agent_summary, m.needs_reply, m.analyzed_at,
                       COALESCE(a.status, 'open') AS attention_status,
                       a.owner_note, a.updated_at AS attention_updated_at
                  FROM messages AS m
                  LEFT JOIN message_attention AS a
                    ON a.mailbox_id=m.mailbox_id
                   AND a.message_id=COALESCE(NULLIF(m.remote_id, ''), NULLIF(m.internet_message_id, ''), CAST(m.uid AS TEXT))
                 WHERE (
                        m.needs_reply=1
                        OR m.agent_priority IN ('high', 'urgent')
                        OR m.agent_category='security'
                       )
                   AND COALESCE(a.status, 'open')='open'
                   {where_mailbox}
                 ORDER BY
                       CASE m.agent_priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                       CASE WHEN m.needs_reply=1 THEN 0 ELSE 1 END,
                       m.uid DESC
                 LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def resolve_attention(
        self,
        mailbox_id: str,
        message_id: str,
        *,
        owner_note: str | None = None,
    ) -> dict[str, Any]:
        if self.get_message(mailbox_id, message_id) is None:
            raise KeyError(message_id)
        now = utc_now()
        note = (owner_note or "").strip() or None
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO message_attention (
                    mailbox_id, message_id, status, owner_note, created_at, updated_at
                ) VALUES (?, ?, 'resolved', ?, ?, ?)
                ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                    status='resolved', owner_note=excluded.owner_note, updated_at=excluded.updated_at
                """,
                (mailbox_id, message_id, note, now, now),
            )
        return {
            "mailbox_id": mailbox_id,
            "message_id": message_id,
            "status": "resolved",
            "owner_note": note,
            "updated_at": now,
        }

'''
replace_once(
    "apps/gateway/mail_agent_gateway/mail_store.py",
    "\n    def enqueue_approval(\n",
    "\n" + attention_methods + "    def enqueue_approval(\n",
)

# ---------------------------------------------------------------------------
# Runtime deterministic handling + non-fatal mark-read post-processing.
# ---------------------------------------------------------------------------
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    "    MailActionType,\n    RuleMode,",
    "    MailActionType,\n    MailCategory,\n    MailHandlingAction,\n    RuleMode,",
)
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    """            analysis.proposal.priority = priority
            analysis.proposal.category = category

            if rule_mode == RuleMode.DRAFT_ONLY""",
    """            analysis.proposal.priority = priority
            analysis.proposal.category = category

            category_action = MailHandlingAction.NONE
            if rule_mode == RuleMode.NORMAL:
                if category == MailCategory.NEWSLETTER:
                    category_action = behavior.newsletter_action
                elif category == MailCategory.ADVERTISING:
                    category_action = behavior.advertising_action
            if category_action != MailHandlingAction.NONE:
                metadata = dict(analysis.proposal.metadata)
                metadata["deterministic_category_handling"] = category.value
                metadata["model_proposed_action"] = analysis.proposal.action.value
                analysis.proposal.metadata = metadata
                analysis.proposal.action = MailActionType(category_action.value)
                analysis.policy = self.mail_agent.policy_engine.evaluate(profile, analysis.proposal)

            if rule_mode == RuleMode.DRAFT_ONLY""",
)
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    """        behavior = self.behavior(config)
        self._ensure_brain(config)
        queue = (""",
    """        behavior = self.behavior(config)
        _, profile = self._ensure_brain(config)
        queue = (""",
)
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    """        below_confidence = 0
        errors = 0
        provider_name""",
    """        below_confidence = 0
        errors = 0
        marked_read = 0
        postprocess_errors = 0
        provider_name""",
)
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    """                processed += 1
            except Exception as exc:""",
    """                if (
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
                            priority=analysis_priority if False else MailCategory.OTHER,  # replaced below
                        )
                processed += 1
            except Exception as exc:""",
)
# Replace the intentionally unique temporary constructor with the final, type-correct block.
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    """                        read_proposal = MailActionProposal(
                            action=MailActionType.MARK_READ,
                            mailbox_id=mailbox_id,
                            message_id=context.message_id,
                            thread_id=context.thread_id,
                            confidence=1.0,
                            reason="Besitzer-Einstellung: erfolgreich bearbeitete Mail als gelesen markieren.",
                            priority=analysis_priority if False else MailCategory.OTHER,  # replaced below
                        )""",
    """                        read_proposal = MailActionProposal(
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
                                )""",
)
replace_once(
    "apps/gateway/mail_agent_gateway/agent_runtime.py",
    '            "errors": errors,\n            "pending_before": pending_before,',
    '            "errors": errors,\n            "marked_read": marked_read,\n            "postprocess_errors": postprocess_errors,\n            "pending_before": pending_before,',
)
replace_once(
    "packages/agent_core/mail_agent_core/brain.py",
    '            "errors",\n            "pending_before",',
    '            "errors",\n            "marked_read",\n            "postprocess_errors",\n            "pending_before",',
)

# ---------------------------------------------------------------------------
# Attention API.
# ---------------------------------------------------------------------------
replace_once(
    "apps/gateway/mail_agent_gateway/schemas.py",
    """class LearningDecisionRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class AgentRunRequest""",
    """class LearningDecisionRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class AttentionResolveRequest(BaseModel):
    mailbox_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=1024)
    owner_note: str | None = Field(default=None, max_length=4000)
    actor: str = Field(default="local-user", min_length=1, max_length=200)


class AgentRunRequest""",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "    AgentAnalyzeRequest,\n    AgentRunRequest,",
    "    AgentAnalyzeRequest,\n    AgentRunRequest,\n    AttentionResolveRequest,",
)
attention_routes = '''
@app.get("/v1/attention")
async def list_attention(mailbox_id: str | None = None, limit: int = 100) -> dict:
    _configuration_or_409()
    return {"attention": mail_store.list_attention(mailbox_id, limit)}


@app.post("/v1/attention/resolve")
async def resolve_attention(body: AttentionResolveRequest) -> dict:
    _configuration_or_409()
    try:
        item = mail_store.resolve_attention(
            body.mailbox_id,
            body.message_id,
            owner_note=body.owner_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Attention message not found") from exc
    audit_log.append(
        "owner_attention_resolved",
        actor=body.actor,
        details={"mailbox_id": body.mailbox_id, "message_id": body.message_id},
    )
    return item


'''
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    '@app.get("/v1/drafts")\nasync def list_drafts',
    attention_routes + '@app.get("/v1/drafts")\nasync def list_drafts',
)

# ---------------------------------------------------------------------------
# Desktop important-mail notifications now land in Handlungsbedarf.
# ---------------------------------------------------------------------------
text = read("apps/launcher/mail_agent_launcher/desktop_runtime.py")
if 'view="inbox"' not in text:
    raise SystemExit("Expected priority notification inbox target")
text = text.replace('view="inbox"', 'view="attention"')
write("apps/launcher/mail_agent_launcher/desktop_runtime.py", text)
replace_once(
    "apps/web/desktop-links.js",
    "    'inbox',\n    'approvals',",
    "    'inbox',\n    'attention',\n    'approvals',",
)

# ---------------------------------------------------------------------------
# Dedicated lightweight attention/settings enhancement UI.
# ---------------------------------------------------------------------------
attention_js = r'''(() => {
  const apiBase = location.origin;
  let attention = [];
  let settingsCache = null;
  let renderingAttention = false;

  const escHtml = value => String(value ?? '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const request = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const notify = (text, kind = 'success') => {
    if (typeof window.showNotice === 'function') window.showNotice(text, kind);
  };
  const messageId = item => String(item.remote_id || item.internet_message_id || item.uid || '');
  const isAttentionRoute = () => new URLSearchParams(location.search).get('view') === 'attention';

  async function loadAttention() {
    const data = await request('/v1/attention?limit=200');
    attention = data.attention || [];
    updateNavBadge();
    return attention;
  }

  function attentionLabel(item) {
    if (item.needs_reply === true) return 'Antwort / Entscheidung nötig';
    if (item.agent_priority === 'urgent') return 'Dringend';
    if (item.agent_category === 'security') return 'Sicherheitsrelevant';
    return 'Wichtig';
  }

  function attentionCard(item) {
    const id = messageId(item);
    const summary = item.agent_summary || 'Der Agent hat diese Mail als relevant für deine Aufmerksamkeit eingestuft.';
    const priority = item.agent_priority || 'normal';
    const category = item.agent_category || 'other';
    return `<article class="attention-card">
      <div class="attention-head"><div><span class="attention-kicker">${escHtml(attentionLabel(item))}</span><h3>${escHtml(item.subject || '(ohne Betreff)')}</h3><p>${escHtml(item.sender || '')}</p></div><span class="intel-badge ${escHtml(priority)}">${escHtml(priority)}</span></div>
      <div class="attention-tags"><span>${escHtml(category)}</span>${item.needs_reply === true ? '<span>Antwort nötig</span>' : ''}</div>
      <p class="attention-summary">${escHtml(summary)}</p>
      <label class="field"><span>Meine Rückmeldung / Notiz</span><textarea rows="3" data-attention-note="${escHtml(id)}" placeholder="Optional: Entscheidung, Kontext oder Notiz für dich …">${escHtml(item.owner_note || '')}</textarea></label>
      <div class="inline-actions left"><button class="btn primary compact" data-attention-resolve="${escHtml(id)}" data-mailbox="${escHtml(item.mailbox_id)}">Erledigt / Rückmeldung speichern</button></div>
    </article>`;
  }

  async function renderAttention() {
    if (renderingAttention) return;
    renderingAttention = true;
    try {
      await loadAttention();
      const body = document.querySelector('.workspace-body');
      if (!body) return;
      const title = document.querySelector('.topbar h1');
      if (title) title.textContent = 'Handlungsbedarf';
      body.innerHTML = `<div class="attention-center"><section class="panel attention-hero"><div><span class="hero-kicker">DEINE ENTSCHEIDUNGEN</span><h2>Was deine Aufmerksamkeit braucht.</h2><p>Hier bündelt MAIL-AGENT wichtige, dringende, sicherheitsrelevante oder antwortbedürftige Mails. Freigaben für riskante Aktionen bleiben separat in der Freigabe-Queue.</p></div><span class="badge">${attention.length} OFFEN</span></section><section class="panel full"><div class="panel-head"><div><span>WARTET AUF DICH</span><h3>Handlungsbedarf</h3></div><button class="btn secondary compact" id="attention-refresh">Aktualisieren</button></div>${attention.length ? `<div class="attention-list">${attention.map(attentionCard).join('')}</div>` : '<div class="empty-state large"><b>Alles erledigt</b><span>Aktuell wartet keine wichtige Mail auf deine Aufmerksamkeit.</span></div>'}</section></div>`;
      document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === 'attention'));
      document.getElementById('attention-refresh')?.addEventListener('click', renderAttention);
      document.querySelectorAll('[data-attention-resolve]').forEach(button => button.addEventListener('click', async () => {
        const id = button.dataset.attentionResolve;
        const mailboxId = button.dataset.mailbox;
        const note = document.querySelector(`[data-attention-note="${CSS.escape(id)}"]`)?.value?.trim() || null;
        button.disabled = true;
        try {
          await request('/v1/attention/resolve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mailbox_id:mailboxId,message_id:id,owner_note:note,actor:'local-user'})});
          notify('Handlungsbedarf als erledigt markiert.');
          await renderAttention();
        } catch (error) {
          notify(error.message, 'error');
          button.disabled = false;
        }
      }));
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      renderingAttention = false;
    }
  }

  function updateNavBadge() {
    const button = document.querySelector('[data-view="attention"]');
    if (!button) return;
    let badge = button.querySelector('b');
    if (attention.length) {
      if (!badge) { badge = document.createElement('b'); button.appendChild(badge); }
      badge.textContent = String(attention.length);
    } else if (badge) badge.remove();
  }

  function injectAttentionNav() {
    const nav = document.querySelector('.sidebar nav');
    if (!nav || nav.querySelector('[data-view="attention"]')) return;
    const button = document.createElement('button');
    button.className = 'nav-item';
    button.dataset.view = 'attention';
    button.innerHTML = `<svg class="icon" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z"/><path d="M12 8v5"/><path d="M12 17h.01"/></svg><span>Handlungsbedarf</span>`;
    const approvals = nav.querySelector('[data-view="approvals"]');
    nav.insertBefore(button, approvals || null);
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      history.replaceState({}, '', '/?view=attention');
      renderAttention();
    });
    updateNavBadge();
  }

  async function injectMailAutomationSettings() {
    const marker = document.getElementById('behavior-auto-drafts');
    if (!marker || document.getElementById('behavior-mail-automation')) return;
    try {
      settingsCache = await request('/v1/settings');
      const behavior = settingsCache.behavior || {};
      const row = marker.closest('.setting-row');
      if (!row) return;
      const wrapper = document.createElement('div');
      wrapper.id = 'behavior-mail-automation';
      wrapper.className = 'mail-automation-settings';
      const options = value => `<option value="none" ${value==='none'?'selected':''}>Nur analysieren</option><option value="mark_read" ${value==='mark_read'?'selected':''}>Automatisch als gelesen markieren</option><option value="archive" ${value==='archive'?'selected':''}>Automatisch archivieren, wenn Policy erlaubt</option>`;
      wrapper.innerHTML = `<div class="setting-row"><span>Erfolgreich abgearbeitete Mails im Postfach als gelesen markieren</span><input id="behavior-mark-processed-read" type="checkbox" ${behavior.mark_processed_read !== false ? 'checked' : ''}></div><div class="form-grid two"><label class="field"><span>Newsletter automatisch behandeln</span><select id="behavior-newsletter-action">${options(behavior.newsletter_action || 'none')}</select></label><label class="field"><span>Werbung automatisch behandeln</span><select id="behavior-advertising-action">${options(behavior.advertising_action || 'none')}</select></label></div><div class="security-note"><span>Archivieren bleibt an Autonomie und Policy Engine gebunden. Shadow Mode verändert niemals das Postfach.</span></div><div class="inline-actions left"><button class="btn secondary compact" id="save-mail-automation">Mail-Automatik speichern</button></div>`;
      row.insertAdjacentElement('afterend', wrapper);
      document.getElementById('save-mail-automation')?.addEventListener('click', async () => {
        const latest = await request('/v1/settings');
        const next = {...(latest.behavior || {}), mark_processed_read:!!document.getElementById('behavior-mark-processed-read')?.checked, newsletter_action:document.getElementById('behavior-newsletter-action')?.value || 'none', advertising_action:document.getElementById('behavior-advertising-action')?.value || 'none'};
        try {
          settingsCache = await request('/v1/settings/behavior', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({behavior:next})});
          if (typeof window.loadRuntimeSettings === 'function') await window.loadRuntimeSettings(true);
          notify('Mail-Automatik gespeichert.');
        } catch (error) {
          notify(error.message, 'error');
        }
      });
    } catch (error) {
      // Settings remain usable even if this enhancement cannot load.
    }
  }

  function enhance() {
    injectAttentionNav();
    injectMailAutomationSettings();
    loadAttention().catch(() => undefined);
    if (isAttentionRoute()) renderAttention();
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-view]');
    if (!target || target.dataset.view === 'attention') return;
    if (isAttentionRoute()) {
      const view = target.dataset.view;
      history.replaceState({}, '', view === 'overview' ? '/' : `/?view=${encodeURIComponent(view)}`);
    }
  }, true);

  const app = document.getElementById('app');
  if (app) {
    new MutationObserver(() => setTimeout(enhance, 0)).observe(app, {childList:true});
  }
  setTimeout(enhance, 0);
  window.setInterval(() => loadAttention().catch(() => undefined), 30000);
})();
'''
write("apps/web/attention-center.js", attention_js)
write(
    "apps/web/attention-center.css",
    '''.attention-center{display:grid;gap:18px}.attention-hero{display:flex;align-items:center;justify-content:space-between;gap:20px}.attention-hero h2{margin:6px 0 8px}.attention-list{display:grid;gap:14px}.attention-card{border:1px solid var(--line,#24324a);border-radius:18px;padding:18px;background:rgba(10,18,31,.6)}.attention-head{display:flex;justify-content:space-between;gap:16px}.attention-head h3{margin:5px 0}.attention-head p{margin:0;color:var(--muted,#91a4c2)}.attention-kicker{font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:#8fb5ff}.attention-tags{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.attention-tags span{font-size:12px;padding:5px 9px;border-radius:999px;background:rgba(110,130,255,.12);border:1px solid rgba(110,130,255,.2)}.attention-summary{line-height:1.55}.mail-automation-settings{display:grid;gap:12px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line,#24324a)}
''',
)

# Cache-bust all current static assets and load the enhancement.
index = read("apps/web/index.html")
index = re.sub(r"\?v=0\.13\.\d+", "?v=0.13.8", index)
if "attention-center.css" not in index:
    index = index.replace(
        '<link rel="stylesheet" href="/assets/agent-settings.css?v=0.13.8" />',
        '<link rel="stylesheet" href="/assets/agent-settings.css?v=0.13.8" />\n  <link rel="stylesheet" href="/assets/attention-center.css?v=0.13.8" />',
    )
if "attention-center.js" not in index:
    index = index.replace(
        '<script src="/assets/desktop-links.js?v=0.13.8" defer></script>',
        '<script src="/assets/attention-center.js?v=0.13.8" defer></script>\n  <script src="/assets/desktop-links.js?v=0.13.8" defer></script>',
    )
write("apps/web/index.html", index)

# Build syntax validation for the new JS.
workflow = read(".github/workflows/build-installers.yml")
workflow = workflow.replace(
    "node --check apps/web/desktop-links.js",
    "node --check apps/web/desktop-links.js\n          node --check apps/web/attention-center.js",
)
write(".github/workflows/build-installers.yml", workflow)

# ---------------------------------------------------------------------------
# Regression tests.
# ---------------------------------------------------------------------------
write(
    "tests/test_agent_queue_claims.py",
    '''from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mail_agent_gateway.agent_queue import AgentWorkQueue
from mail_agent_gateway.mail_store import MailStore, StoredMessage


def _message(uid: int) -> StoredMessage:
    return StoredMessage(
        mailbox_id="mb-1",
        uid=uid,
        internet_message_id=f"<m-{uid}@example.test>",
        thread_key=f"thread-{uid}",
        sender="sender@example.test",
        recipients=["owner@example.test"],
        subject=f"Message {uid}",
        sent_at=None,
        body_text="hello",
        seen=False,
        remote_id=f"remote-{uid}",
    )


def test_overlapping_cycles_can_claim_a_message_only_once(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1)])
    queue_a = AgentWorkQueue(store)
    queue_b = AgentWorkQueue(store)
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(queue: AgentWorkQueue) -> None:
        barrier.wait()
        results.append(len(queue.list_pending("mb-1", 1)))

    threads = [threading.Thread(target=worker, args=(queue_a,)), threading.Thread(target=worker, args=(queue_b,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sorted(results) == [0, 1]
    assert queue_a.pending_count("mb-1") == 0


def test_error_and_stale_running_claims_are_retryable(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1), _message(2)])
    queue = AgentWorkQueue(store)
    claimed = queue.list_pending("mb-1", 2)
    assert len(claimed) == 2

    store.record_agent_processing("mb-1", "remote-1", status="error", error="temporary")
    retry = queue.list_pending("mb-1", 1)
    assert [item["remote_id"] for item in retry] == ["remote-1"]

    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE agent_processing SET processed_at=? WHERE message_id='remote-2'", (old,))
    stale_retry = queue.list_pending("mb-1", 2)
    assert "remote-2" in {item["remote_id"] for item in stale_retry}
''',
)
write(
    "tests/test_attention_store.py",
    '''from __future__ import annotations

from pathlib import Path

from mail_agent_gateway.mail_store import MailStore, StoredMessage


def _message(uid: int) -> StoredMessage:
    return StoredMessage(
        mailbox_id="mb-1",
        uid=uid,
        internet_message_id=f"<m-{uid}@example.test>",
        thread_key=f"thread-{uid}",
        sender="sender@example.test",
        recipients=["owner@example.test"],
        subject=f"Message {uid}",
        sent_at=None,
        body_text="hello",
        seen=False,
        remote_id=f"remote-{uid}",
    )


def test_attention_collects_important_and_reply_needed_mail(tmp_path: Path):
    store = MailStore(tmp_path / "mail.db")
    store.upsert_messages([_message(1), _message(2), _message(3)])
    store.update_message_intelligence("mb-1", "remote-1", priority="high", category="work", summary="Important", needs_reply=False)
    store.update_message_intelligence("mb-1", "remote-2", priority="normal", category="support", summary="Reply", needs_reply=True)
    store.update_message_intelligence("mb-1", "remote-3", priority="normal", category="newsletter", summary="Noise", needs_reply=False)

    items = store.list_attention("mb-1")
    assert {item["remote_id"] for item in items} == {"remote-1", "remote-2"}

    store.resolve_attention("mb-1", "remote-1", owner_note="Erledigt")
    items = store.list_attention("mb-1")
    assert {item["remote_id"] for item in items} == {"remote-2"}
''',
)
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


def test_runtime_applies_category_handling_and_nonfatal_mark_read_postprocess():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    assert 'metadata["deterministic_category_handling"]' in source
    assert "behavior.newsletter_action" in source
    assert "behavior.advertising_action" in source
    assert "behavior.mark_processed_read" in source
    assert "agent_postprocess_mark_read_failed" in source
    assert "read_policy.allowed and not read_policy.requires_approval" in source


def test_shadow_cycle_stays_remote_side_effect_free():
    source = (ROOT / "apps/gateway/mail_agent_gateway/agent_runtime.py").read_text(encoding="utf-8")
    shadow = source[source.index("async def _run_shadow_mailbox"):source.index("async def run_mailbox")]
    assert "execute_direct(read_proposal)" not in shadow
''',
)
write(
    "tests/test_attention_ui_contract.py",
    '''from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_attention_ui_and_routes_are_wired():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/attention-center.js").read_text(encoding="utf-8")
    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")
    desktop = (ROOT / "apps/launcher/mail_agent_launcher/desktop_runtime.py").read_text(encoding="utf-8")

    assert "/assets/attention-center.js?v=0.13.8" in index
    assert "/assets/attention-center.css?v=0.13.8" in index
    assert "Handlungsbedarf" in js
    assert "/v1/attention?limit=200" in js
    assert "/v1/attention/resolve" in js
    assert '@app.get("/v1/attention")' in main
    assert '@app.post("/v1/attention/resolve")' in main
    assert 'view="attention"' in desktop


def test_attention_observer_is_not_recursive():
    js = (ROOT / "apps/web/attention-center.js").read_text(encoding="utf-8")
    assert ".observe(app, {childList:true})" in js
    assert "subtree:true" not in js.replace(" ", "")


def test_attention_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    result = subprocess.run([node, "--check", str(ROOT / "apps/web/attention-center.js")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
''',
)

# Clean temporary patch infrastructure from the resulting feature commit.
(ROOT / ".github/workflows/apply-0138-patch.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
print("0.13.8 patch applied")
