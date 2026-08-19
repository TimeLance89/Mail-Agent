from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text and old not in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"Expected one marker in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"Expected one regex marker in {path}: {pattern[:120]!r}")
    target.write_text(updated, encoding="utf-8")


def version_replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"Version marker missing in {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


main = "apps/gateway/mail_agent_gateway/main.py"
replace_once(main, "from .cloud_sync import GoogleGmailSyncService\n", "from .cloud_sync import GoogleGmailSyncService\nfrom .draft_service import DraftService\n")
replace_once(
    main,
    "    BehaviorSettingsRequest,\n    LLMSettingsRequest,\n",
    "    BehaviorSettingsRequest,\n    DraftSubmitRequest,\n    DraftUpdateRequest,\n    LLMSettingsRequest,\n",
)
replace_once(
    main,
    '''agent_runtime = AgentRuntime(
    mail_agent=mail_agent,
    identity_manager=identity_manager,
    mail_store=mail_store,
    state_store=state_store,
    providers=providers,
    audit_log=audit_log,
)
_sync_stop = asyncio.Event()
''',
    "_sync_stop = asyncio.Event()\n",
)
replace_once(
    main,
    '''action_executor = MailActionExecutor(
    mail_store=mail_store,
    identity_manager=identity_manager,
    vault=vault,
    mailbox_lookup=_mailbox_by_id,
    google_client_id=settings.google_client_id,
    google_client_secret=settings.google_client_secret,
    audit_log=audit_log,
)
''',
    '''action_executor = MailActionExecutor(
    mail_store=mail_store,
    identity_manager=identity_manager,
    vault=vault,
    mailbox_lookup=_mailbox_by_id,
    google_client_id=settings.google_client_id,
    google_client_secret=settings.google_client_secret,
    audit_log=audit_log,
)
agent_runtime = AgentRuntime(
    mail_agent=mail_agent,
    identity_manager=identity_manager,
    mail_store=mail_store,
    state_store=state_store,
    providers=providers,
    audit_log=audit_log,
    action_executor=action_executor,
)
draft_service = DraftService(
    mail_store=mail_store,
    identity_manager=identity_manager,
    state_store=state_store,
    policy_engine=policy_engine,
    audit_log=audit_log,
)
''',
)
version_replace(main, 'APP_VERSION = "0.5.0"', 'APP_VERSION = "0.6.0"')
replace_once(
    main,
    '            "approved_send_executes_immediately": True,\n',
    '            "approved_send_executes_immediately": True,\n            "mailbox_mutations_policy_gated": True,\n            "draft_edits_are_resigned": True,\n            "delete_means_trash": True,\n',
)
regex_once(
    main,
    r'@app\.get\("/v1/drafts"\)\nasync def list_drafts\(mailbox_id: str \| None = None, limit: int = 100\) -> dict:\n.*?(?=\n\n@app\.get\("/v1/approvals"\))',
    '''@app.get("/v1/drafts")
async def list_drafts(mailbox_id: str | None = None, limit: int = 100) -> dict:
    return {
        "drafts": [
            draft_service.public_draft(item)
            for item in mail_store.list_drafts(mailbox_id, limit)
        ]
    }


@app.get("/v1/drafts/{draft_id}")
async def get_draft(draft_id: str) -> dict:
    try:
        return draft_service.public_draft(mail_store.get_draft(draft_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc


@app.put("/v1/drafts/{draft_id}")
async def update_draft(draft_id: str, body: DraftUpdateRequest) -> dict:
    try:
        return draft_service.edit(
            draft_id,
            subject=body.subject,
            body=body.body,
            recipient=body.recipient,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/drafts/{draft_id}/submit")
async def submit_draft(draft_id: str, body: DraftSubmitRequest) -> dict:
    try:
        return draft_service.submit_for_approval(draft_id, actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Draft not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc''',
)

for path, old, new in [
    ("pyproject.toml", 'version = "0.5.0"', 'version = "0.6.0"'),
    ("apps/launcher/mail_agent_launcher/main.py", 'APP_VERSION = "0.5.0"', 'APP_VERSION = "0.6.0"'),
    ("packaging/windows/MailAgent.iss", '#define MyAppVersion "0.5.0"', '#define MyAppVersion "0.6.0"'),
    ("packages/agent_core/mail_agent_core/identity.py", 'app_version: str = "0.5.0"', 'app_version: str = "0.6.0"'),
]:
    version_replace(path, old, new)

app = "apps/web/app.js"
text = Path(app).read_text(encoding="utf-8")
text = text.replace("MAIL-AGENT v0.5.0", "MAIL-AGENT v0.6.0")
text = re.sub(r"const current=updateStatus\?\.current_version\|\|'0\.[0-9]+\.0';", "const current=updateStatus?.current_version||'0.6.0';", text, count=1)
text = text.replace("let settingsProbe = null;", "let settingsProbe = null;\nlet editingDraftId = null;")
Path(app).write_text(text, encoding="utf-8")

regex_once(
    app,
    r'function approvalCard\(item\)\{.*?\}\nfunction draftCard',
    '''function approvalCard(item){const p=item.proposal||{};const failed=item.status==='approved'&&item.execution_status==='failed';const sends=['send_reply','forward'].includes(item.action);const status=failed?`<span class="delivery-failed">Ausführung fehlgeschlagen · ${esc(item.execution_error||'erneut versuchen')}</span>`:`<span>Risiko: ${esc(item.policy?.risk||'')}</span>`;const retryLabel=sends?'Erneut senden':'Erneut ausführen';const approveLabel=sends?'Freigeben & senden':'Freigeben & ausführen';const actions=failed?`<button class="btn primary compact" data-execute="${esc(item.approval_id)}">${icon('sync',15)} ${retryLabel}</button>`:`<button class="btn secondary compact" data-reject="${esc(item.approval_id)}">${icon('x',15)} Ablehnen</button><button class="btn primary compact" data-approve="${esc(item.approval_id)}">${icon('check',15)} ${approveLabel}</button>`;return `<article class="approval"><span class="risk-icon">${icon('shield',19)}</span><div class="approval-copy"><div class="mail-line"><b>${esc(item.action)}</b>${status}</div><h4>${esc(p.subject||p.destination_folder||p.recipient||'Mail-Aktion')}</h4><p>${esc(p.summary||p.reason||item.policy?.reason||'')}</p></div><div class="approval-actions">${actions}</div></article>`;}
function draftCard''',
)
regex_once(
    app,
    r'function draftCard\(item\)\{.*?\}\n\n\nfunction checked',
    '''function draftCard(item){
  const editable=item.status!=='sent';
  const editing=editingDraftId===item.draft_id;
  const proposal=item.proposal||{};
  const replyLocked=item.source_action==='send_reply'||proposal.metadata?.drafted_from_action==='send_reply';
  if(editing){return `<article class="draft-card draft-editor"><div class="draft-head"><span>${icon('draft',18)}</span><div><b>Entwurf bearbeiten</b><small>Revision ${esc(item.revision||1)} · beim Speichern wird neu signiert</small></div><span class="badge soft">${esc(item.status)}</span></div><div class="form-grid two"><label class="field"><span>Empfänger</span><input data-draft-recipient value="${esc(item.recipient||'')}" ${replyLocked?'disabled':''}></label><label class="field"><span>Betreff</span><input data-draft-subject value="${esc(item.subject||'')}"></label></div><label class="field"><span>Nachricht</span><textarea data-draft-body rows="10">${esc(item.editable_body||'')}</textarea></label><div class="security-note">${icon('shield',18)}<span>Der Agent-ID-Block ist absichtlich nicht editierbar. MAIL-AGENT erzeugt und signiert ihn nach dem Speichern neu.</span></div><div class="draft-actions"><button class="btn text compact" data-draft-cancel>Abbrechen</button><button class="btn primary compact" data-draft-save="${esc(item.draft_id)}">Speichern & neu signieren</button></div></article>`;}
  const submit=!item.approval_id&&editable?`<button class="btn primary compact" data-draft-submit="${esc(item.draft_id)}">${icon('shield',15)} Zur Freigabe</button>`:'';
  const edit=editable?`<button class="btn secondary compact" data-draft-edit="${esc(item.draft_id)}">Bearbeiten</button>`:'';
  return `<article class="draft-card"><div class="draft-head"><span>${icon('draft',18)}</span><div><b>${esc(item.subject||'(ohne Betreff)')}</b><small>An ${esc(item.recipient||'offen')} · Revision ${esc(item.revision||1)}</small></div><span class="badge soft">${esc(item.status)}</span></div><p>${esc(String(item.editable_body||item.body||'').slice(0,320))}${String(item.editable_body||item.body||'').length>320?'…':''}</p><div class="draft-actions">${edit}${submit}${item.approval_id?'<span class="muted">Freigabe offen</span>':''}</div></article>`;
}


function checked''',
)
replace_once(
    app,
    "  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));\n",
    "  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));\n  document.querySelectorAll('[data-draft-edit]').forEach(el=>el.onclick=()=>{editingDraftId=el.dataset.draftEdit;render();});\n  document.querySelectorAll('[data-draft-cancel]').forEach(el=>el.onclick=()=>{editingDraftId=null;render();});\n  document.querySelectorAll('[data-draft-save]').forEach(el=>el.onclick=()=>saveDraft(el.dataset.draftSave));\n  document.querySelectorAll('[data-draft-submit]').forEach(el=>el.onclick=()=>submitDraft(el.dataset.draftSubmit));\n",
)
replace_once(
    app,
    "async function retryApproval(id){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/execute`,{});await loadDashboard(true);showNotice(result.execution_status==='sent'?'Nachricht wurde gesendet.':'Versandstatus aktualisiert.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}",
    '''async function retryApproval(id){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/execute`,{});await loadDashboard(true);showNotice(result.execution_status==='sent'?'Nachricht wurde gesendet.':'Aktion wurde ausgeführt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}
async function saveDraft(id){const card=document.querySelector('.draft-editor');if(!card)return;const body=card.querySelector('[data-draft-body]')?.value||'';const subject=card.querySelector('[data-draft-subject]')?.value||'';const recipient=card.querySelector('[data-draft-recipient]')?.value||null;try{await put(`/v1/drafts/${encodeURIComponent(id)}`,{subject,body,recipient,actor:'local-user'});editingDraftId=null;await loadDashboard(true);showNotice('Entwurf gespeichert und kryptografisch neu signiert.');render();}catch(e){showNotice(e.message,'error');}}
async function submitDraft(id){try{await post(`/v1/drafts/${encodeURIComponent(id)}/submit`,{actor:'local-user'});await loadDashboard(true);showNotice('Entwurf wartet jetzt auf Freigabe.');render();}catch(e){showNotice(e.message,'error');}}''',
)
replace_once(
    app,
    "async function decideApproval(id,decision){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);showNotice(decision==='approve'?(result.execution_status==='sent'?'Freigegeben und gesendet.':'Aktion freigegeben.'):'Aktion abgelehnt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}",
    "async function decideApproval(id,decision){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);const done=result.execution_status==='sent'?'Freigegeben und gesendet.':result.execution_status==='completed'?'Freigegeben und ausgeführt.':'Aktion freigegeben.';showNotice(decision==='approve'?done:'Aktion abgelehnt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}",
)

css = "apps/web/agent-settings.css"
with Path(css).open("a", encoding="utf-8") as handle:
    handle.write("\n.draft-actions{display:flex;align-items:center;gap:8px;justify-content:flex-end;margin-top:12px}.draft-editor .form-grid{margin-top:16px}.draft-editor textarea{width:100%;min-height:210px;border:1px solid var(--line);background:#090e17;color:#e9eef7;border-radius:12px;padding:13px 14px;outline:none;resize:vertical}.draft-editor textarea:focus{border-color:#6574d8;box-shadow:0 0 0 3px #6c79db16}.draft-editor input:disabled{opacity:.65;cursor:not-allowed}@media(max-width:760px){.draft-actions{justify-content:flex-start;flex-wrap:wrap}}\n")
