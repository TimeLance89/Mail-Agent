from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text and old not in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one marker in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"Expected exactly one regex marker in {path}: {pattern[:100]!r}")
    target.write_text(updated, encoding="utf-8")


# Gateway integration.
main = "apps/gateway/mail_agent_gateway/main.py"
replace_once(
    main,
    "from .agent_runtime import AgentRuntime\n",
    "from .action_executor import MailActionExecutor\nfrom .agent_runtime import AgentRuntime\n",
)
replace_once(
    main,
    "\n\nasync def _sync_mailbox(mailbox: dict, *, limit: int = 100) -> dict:\n",
    """

action_executor = MailActionExecutor(
    mail_store=mail_store,
    identity_manager=identity_manager,
    vault=vault,
    mailbox_lookup=_mailbox_by_id,
    google_client_id=settings.google_client_id,
    google_client_secret=settings.google_client_secret,
    audit_log=audit_log,
)


async def _sync_mailbox(mailbox: dict, *, limit: int = 100) -> dict:
""",
)
replace_once(main, 'APP_VERSION = "0.4.0"', 'APP_VERSION = "0.5.0"')
replace_once(
    main,
    '            "send_requires_approval": True,\n',
    '            "send_requires_approval": True,\n            "approved_send_executes_immediately": True,\n',
)
regex_once(
    main,
    r'@app\.get\("/v1/approvals"\)\nasync def list_approvals\(status: str = "pending", limit: int = 100\) -> dict:\n.*?(?=\n\n@app\.post\("/v1/approvals/\{approval_id\}/approve"\))',
    '''@app.get("/v1/approvals")
async def list_approvals(status: str = "pending", limit: int = 100) -> dict:
    if status == "attention":
        pending = mail_store.list_approvals("pending", limit)
        failed = [
            item
            for item in mail_store.list_approvals("approved", limit)
            if item.get("execution_status") == "failed"
        ]
        combined = sorted(pending + failed, key=lambda item: item.get("created_at") or "", reverse=True)
        return {"approvals": combined[:limit]}
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Unsupported approval status")
    return {"approvals": mail_store.list_approvals(status, limit)}''',
)
regex_once(
    main,
    r'@app\.post\("/v1/approvals/\{approval_id\}/approve"\)\nasync def approve_action\(approval_id: str, body: ApprovalDecisionRequest\) -> dict:\n.*?(?=\n\n@app\.post\("/v1/approvals/\{approval_id\}/reject"\))',
    '''@app.post("/v1/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, body: ApprovalDecisionRequest) -> dict:
    try:
        approval = mail_store.decide_approval(approval_id, decision="approved", actor=body.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append(
        "approval_approved",
        actor=body.actor,
        details={"approval_id": approval_id, "action": approval["action"]},
    )
    if approval.get("execution_status") == "ready":
        try:
            approval = await action_executor.execute_approval(approval_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return approval


@app.post("/v1/approvals/{approval_id}/execute")
async def execute_approved_action(approval_id: str) -> dict:
    try:
        return await action_executor.execute_approval(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc''',
)

# Product version surfaces.
for path, old, new in [
    ("pyproject.toml", 'version = "0.4.0"', 'version = "0.5.0"'),
    ("apps/launcher/mail_agent_launcher/main.py", 'APP_VERSION = "0.4.0"', 'APP_VERSION = "0.5.0"'),
    ("packaging/windows/MailAgent.iss", '#define MyAppVersion "0.4.0"', '#define MyAppVersion "0.5.0"'),
    ("packages/agent_core/mail_agent_core/identity.py", 'app_version: str = "0.2.1"', 'app_version: str = "0.5.0"'),
    ("tests/test_update_api.py", 'assert result["current_version"] == "0.4.0"', 'assert result["current_version"] == "0.5.0"'),
]:
    replace_once(path, old, new)

# Web UI integration.
app = "apps/web/app.js"
text = Path(app).read_text(encoding="utf-8")
text = text.replace("MAIL-AGENT v0.4.0", "MAIL-AGENT v0.5.0")
text = text.replace("const current=updateStatus?.current_version||'0.3.0';", "const current=updateStatus?.current_version||'0.5.0';")
Path(app).write_text(text, encoding="utf-8")

regex_once(
    app,
    r'function mailRow\(item\)\{.*?\}\nfunction approvalCard',
    '''function mailRow(item){const preview=String(item.agent_summary||item.body_text||'').replace(/\\s+/g,' ').slice(0,140);const priority=item.agent_priority||'';const category=item.agent_category||'';const intelligence=`<div class="intel-badges">${priority?`<span class="intel-badge ${esc(priority)}">${esc(priority)}</span>`:''}${category?`<span class="intel-badge">${esc(category)}</span>`:''}${item.needs_reply===true?'<span class="intel-badge">Antwort nötig</span>':''}</div>`;return `<article class="mail-row"><span class="mail-avatar">${esc((item.sender||'?').slice(0,1).toUpperCase())}</span><div class="mail-main"><div class="mail-line"><b>${esc(item.sender||'Unbekannt')}</b><span>${esc(item.sent_at?new Date(item.sent_at).toLocaleDateString():'')}</span></div><h4>${esc(item.subject||'(ohne Betreff)')}</h4>${intelligence}<p>${esc(preview)}${String(item.agent_summary||item.body_text||'').length>140?'…':''}</p></div><span class="row-arrow">${icon('chevron',17)}</span></article>`;}
function approvalCard''',
)
regex_once(
    app,
    r'function approvalCard\(item\)\{.*?\}\nfunction draftCard',
    '''function approvalCard(item){const p=item.proposal||{};const failed=item.status==='approved'&&item.execution_status==='failed';const sends=['send_reply','forward'].includes(item.action);const status=failed?`<span class="delivery-failed">Versand fehlgeschlagen · ${esc(item.execution_error||'erneut versuchen')}</span>`:`<span>Risiko: ${esc(item.policy?.risk||'')}</span>`;const actions=failed?`<button class="btn primary compact" data-execute="${esc(item.approval_id)}">${icon('sync',15)} Erneut senden</button>`:`<button class="btn secondary compact" data-reject="${esc(item.approval_id)}">${icon('x',15)} Ablehnen</button><button class="btn primary compact" data-approve="${esc(item.approval_id)}">${icon('check',15)} ${sends?'Freigeben & senden':'Freigeben'}</button>`;return `<article class="approval"><span class="risk-icon">${icon('shield',19)}</span><div class="approval-copy"><div class="mail-line"><b>${esc(item.action)}</b>${status}</div><h4>${esc(p.subject||p.recipient||'Mail-Aktion')}</h4><p>${esc(p.summary||p.reason||item.policy?.reason||'')}</p></div><div class="approval-actions">${actions}</div></article>`;}
function draftCard''',
)
replace_once(
    app,
    "function checked(value){return value?'checked':'';}\nfunction renderAgentSettings(){",
    '''function checked(value){return value?'checked':'';}
function ruleRow(rule,index){const mode=rule.mode||'normal',priority=rule.priority||'',category=rule.category||'';return `<div class="rule-row" data-rule-index="${index}"><input data-rule-field="pattern" value="${esc(rule.pattern||'')}" placeholder="@firma.de oder person@…"><select data-rule-field="mode"><option value="normal" ${mode==='normal'?'selected':''}>Normal</option><option value="analyze_only" ${mode==='analyze_only'?'selected':''}>Nur analysieren</option><option value="draft_only" ${mode==='draft_only'?'selected':''}>Nur Entwurf</option><option value="ignore" ${mode==='ignore'?'selected':''}>Ignorieren</option></select><select data-rule-field="priority"><option value="" ${!priority?'selected':''}>Priorität · automatisch</option><option value="urgent" ${priority==='urgent'?'selected':''}>Urgent</option><option value="high" ${priority==='high'?'selected':''}>High</option><option value="normal" ${priority==='normal'?'selected':''}>Normal</option><option value="low" ${priority==='low'?'selected':''}>Low</option></select><select data-rule-field="category"><option value="" ${!category?'selected':''}>Kategorie · automatisch</option>${['personal','work','finance','support','sales','newsletter','notification','security','other'].map(v=>`<option value="${v}" ${category===v?'selected':''}>${v}</option>`).join('')}</select><button class="btn text rule-remove" type="button" data-rule-remove="${index}" title="Regel entfernen">${icon('x',15)}</button></div>`;}
function collectRuleRows(){return [...document.querySelectorAll('.rule-row')].map(row=>{const read=field=>row.querySelector(`[data-rule-field="${field}"]`)?.value?.trim()||'';const priority=read('priority'),category=read('category');return {pattern:read('pattern'),mode:read('mode')||'normal',priority:priority||null,category:category||null};}).filter(rule=>rule.pattern);}
function renderAgentSettings(){''',
)
replace_once(
    app,
    "  const behavior=rs.behavior||{enabled:true,auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[]};",
    "  const behavior=rs.behavior||{enabled:true,auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,thread_context_messages:8,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[],rules:[]};",
)
replace_once(
    app,
    "  const providerDetail=settingsProbe?.provider===provider?settingsProbe.detail:(catalog[provider]?.detail||'Noch nicht geprüft');\n",
    "  const providerDetail=settingsProbe?.provider===provider?settingsProbe.detail:(catalog[provider]?.detail||'Noch nicht geprüft');\n  const ruleRows=(behavior.rules||[]).map(ruleRow).join('');\n",
)
replace_once(
    app,
    '    <section class="panel"><div class="panel-head"><div><span>SICHERHEIT</span><h3>Unverhandelbare Grenzen</h3></div></div>',
    '''    <section class="panel"><div class="panel-head"><div><span>REGELN</span><h3>Absender & Domains deterministisch steuern</h3></div><button class="btn secondary compact" id="settings-add-rule">Regel hinzufügen</button></div><p class="rule-help">Regeln werden nach der LLM-Analyse im Gateway erzwungen. Muster wie <b>@firma.de</b> oder eine vollständige Adresse sind möglich. „Nur Entwurf“ kann einen vorgeschlagenen Versand technisch auf einen Draft herunterstufen.</p><div class="rule-editor">${ruleRows||'<div class="empty-state">Noch keine speziellen Regeln.</div>'}</div><div class="security-note">${icon('shield',18)}<span>Priorität und Kategorie können pro Regel fest vorgegeben werden; leer bedeutet automatische Klassifikation.</span></div></section>
    <section class="panel"><div class="panel-head"><div><span>SICHERHEIT</span><h3>Unverhandelbare Grenzen</h3></div></div>''',
)
regex_once(
    app,
    r'async function saveBehaviorSettings\(\)\{.*?(?=\nasync function runAgentNow)',
    '''async function saveBehaviorSettings(){
  const days=[...document.querySelectorAll('[data-agent-day]:checked')].map(el=>Number(el.dataset.agentDay));
  const blocked=(document.getElementById('behavior-blocked-senders')?.value||'').split(/[\\n,]+/).map(v=>v.trim()).filter(Boolean);
  const current=runtimeSettings?.behavior||{};
  const behavior={...current,enabled:!!document.getElementById('behavior-enabled')?.checked,auto_analyze_new_mail:!!document.getElementById('behavior-auto-analyze')?.checked,auto_create_drafts:!!document.getElementById('behavior-auto-drafts')?.checked,minimum_confidence:Number(document.getElementById('behavior-confidence')?.value||0.72),max_messages_per_cycle:Number(document.getElementById('behavior-max-messages')?.value||20),active_from:document.getElementById('behavior-from')?.value||'00:00',active_until:document.getElementById('behavior-until')?.value||'23:59',active_days:days,never_auto_act_senders:blocked,rules:collectRuleRows()};
  try{runtimeSettings=await put('/v1/settings/behavior',{behavior});showNotice('Agentisches Verhalten gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
function addRule(){if(!runtimeSettings)return;const rules=collectRuleRows();rules.push({pattern:'',mode:'normal',priority:null,category:null});runtimeSettings.behavior={...(runtimeSettings.behavior||{}),rules};render();setTimeout(()=>document.querySelector('.rule-row:last-child input')?.focus(),0);}
function removeRule(index){if(!runtimeSettings)return;const rules=collectRuleRows();rules.splice(Number(index),1);runtimeSettings.behavior={...(runtimeSettings.behavior||{}),rules};render();}
''',
)
replace_once(
    app,
    "  document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));\n",
    "  document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));\n  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));\n",
)
replace_once(
    app,
    "  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);\n",
    "  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);\n  document.getElementById('settings-add-rule')?.addEventListener('click',addRule);\n  document.querySelectorAll('[data-rule-remove]').forEach(el=>el.onclick=()=>removeRule(el.dataset.ruleRemove));\n",
)
replace_once(
    app,
    "dashboard.approvals=(await get('/v1/approvals?status=pending&limit=50')).approvals||[];",
    "dashboard.approvals=(await get('/v1/approvals?status=attention&limit=50')).approvals||[];",
)
replace_once(
    app,
    "async function decideApproval(id,decision){try{await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);showNotice(decision==='approve'?'Aktion freigegeben.':'Aktion abgelehnt.');render();}catch(e){showNotice(e.message,'error')}}",
    "async function decideApproval(id,decision){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);showNotice(decision==='approve'?(result.execution_status==='sent'?'Freigegeben und gesendet.':'Aktion freigegeben.'):'Aktion abgelehnt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}\nasync function retryApproval(id){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/execute`,{});await loadDashboard(true);showNotice(result.execution_status==='sent'?'Nachricht wurde gesendet.':'Versandstatus aktualisiert.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}",
)
