from __future__ import annotations

import re
from pathlib import Path

VERSION = "0.8.0"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"Expected exactly one {label} marker, found {text.count(old)}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str, flags: int = 0) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} regex match, found {count}")
    return updated


# Gateway API integration.
main_path = Path("apps/gateway/mail_agent_gateway/main.py")
main = main_path.read_text(encoding="utf-8")
main = replace_once(
    main,
    "from mail_agent_core.models import AgentBehaviorSettings",
    "from mail_agent_core.models import AgentBehaviorSettings, AgentProfile",
    "AgentProfile import",
)
main = replace_once(
    main,
    "    BehaviorSettingsRequest,\n",
    "    BehaviorSettingsRequest,\n    BrainUpdateRequest,\n",
    "BrainUpdateRequest schema import",
)
main = replace_once(
    main,
    "    LLMSettingsRequest,\n",
    "    LLMSettingsRequest,\n    LearningDecisionRequest,\n",
    "LearningDecisionRequest schema import",
)
main = replace_once(
    main,
    "    audit_log=audit_log,\n)\n\n\nasync def _sync_mailbox",
    "    audit_log=audit_log,\n    brain=agent_runtime.brain,\n)\n\n\nasync def _sync_mailbox",
    "DraftService brain wiring",
)
main = replace_once(
    main,
    '        "behavior": behavior.model_dump(mode="json"),\n        "providers": catalog,',
    '        "behavior": behavior.model_dump(mode="json"),\n        "brain": agent_runtime.brain.public_status(),\n        "providers": catalog,',
    "settings brain summary",
)

brain_api = '''\n\ndef _brain_payload() -> dict:\n    _state, config = _configuration_or_409()\n    identity = identity_manager.load()\n    profile = AgentProfile.model_validate(config["profile"])\n    agent_runtime.brain.ensure(identity, profile)\n    snapshot = agent_runtime.brain.snapshot()\n    mailboxes = []\n    for mailbox in _configured_mailboxes():\n        mailbox_id = str(mailbox.get("mailbox_id") or "")\n        if not mailbox_id:\n            continue\n        status = agent_runtime.mailbox_status(mailbox_id)\n        status["email_address"] = mailbox.get("email_address")\n        if not status["enabled"] or not status["auto_analyze_new_mail"]:\n            status["state"] = "paused"\n        elif not status["schedule_active"]:\n            status["state"] = "outside_schedule"\n        elif status["pending"]:\n            status["state"] = "work_pending"\n        else:\n            status["state"] = "idle"\n        mailboxes.append(status)\n    return {\n        "status": agent_runtime.brain.public_status(),\n        "soul": snapshot.soul,\n        "memory": snapshot.memory,\n        "learning_candidates": agent_runtime.brain.learning_candidates(),\n        "recent_activity": agent_runtime.brain.recent_activity(30),\n        "mailboxes": mailboxes,\n        "pending_total": sum(int(item.get("pending") or 0) for item in mailboxes),\n    }\n\n\n@app.get("/v1/agent/brain")\nasync def get_agent_brain() -> dict:\n    return _brain_payload()\n\n\n@app.put("/v1/agent/brain")\nasync def update_agent_brain(body: BrainUpdateRequest) -> dict:\n    if body.soul is None and body.memory is None:\n        raise HTTPException(status_code=400, detail="SOUL.md or MEMORY.md must be supplied")\n    _configuration_or_409()\n    try:\n        agent_runtime.brain.update_owner_memory(soul=body.soul, memory=body.memory)\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    audit_log.append(\n        "agent_brain_owner_memory_changed",\n        actor=body.actor,\n        details={"soul_changed": body.soul is not None, "memory_changed": body.memory is not None},\n    )\n    return _brain_payload()\n\n\n@app.post("/v1/agent/brain/learning/{candidate_id}/accept")\nasync def accept_agent_learning(candidate_id: str, body: LearningDecisionRequest) -> dict:\n    _configuration_or_409()\n    try:\n        candidate = agent_runtime.brain.accept_learning(candidate_id)\n    except KeyError as exc:\n        raise HTTPException(status_code=404, detail="Learning candidate not found") from exc\n    audit_log.append(\n        "agent_learning_accepted",\n        actor=body.actor,\n        details={"candidate_id": candidate_id, "title": candidate.get("title")},\n    )\n    return _brain_payload()\n\n\n@app.post("/v1/agent/brain/learning/{candidate_id}/reject")\nasync def reject_agent_learning(candidate_id: str, body: LearningDecisionRequest) -> dict:\n    _configuration_or_409()\n    try:\n        candidate = agent_runtime.brain.reject_learning(candidate_id)\n    except KeyError as exc:\n        raise HTTPException(status_code=404, detail="Learning candidate not found") from exc\n    audit_log.append(\n        "agent_learning_rejected",\n        actor=body.actor,\n        details={"candidate_id": candidate_id, "title": candidate.get("title")},\n    )\n    return _brain_payload()\n'''
main = replace_once(
    main,
    '\n\n@app.post("/v1/providers/codex/login")',
    brain_api + '\n\n@app.post("/v1/providers/codex/login")',
    "Agent Brain API insertion",
)
main = regex_once(
    main,
    r'(?m)^APP_VERSION = "[^"]+"$',
    f'APP_VERSION = "{VERSION}"',
    "gateway version",
)
main_path.write_text(main, encoding="utf-8")


# Product version synchronization.
version_replacements = [
    (Path("pyproject.toml"), r'(?m)^version = "[^"]+"$', f'version = "{VERSION}"', "pyproject version"),
    (Path("packaging/windows/MailAgent.iss"), r'(?m)^#define MyAppVersion "[^"]+"$', f'#define MyAppVersion "{VERSION}"', "installer version"),
    (Path("apps/launcher/mail_agent_launcher/main.py"), r'(?m)^APP_VERSION = "[^"]+"$', f'APP_VERSION = "{VERSION}"', "launcher version"),
    (Path("packages/agent_core/mail_agent_core/identity.py"), r'app_version: str = "[^"]+"', f'app_version: str = "{VERSION}"', "identity version"),
]
for path, pattern, replacement, label in version_replacements:
    text = path.read_text(encoding="utf-8")
    text = regex_once(text, pattern, replacement, label)
    path.write_text(text, encoding="utf-8")


# Web UI integration.
app_path = Path("apps/web/app.js")
app = app_path.read_text(encoding="utf-8")
app = replace_once(
    app,
    "let runtimeSettings = null;\nlet settingsProbe = null;",
    "let runtimeSettings = null;\nlet brainStatus = null;\nlet brainLoading = false;\nlet settingsProbe = null;",
    "brain globals",
)
app = re.sub(r'MAIL-AGENT v[0-9]+\.[0-9]+\.[0-9]+ · Lokales Gateway', f'MAIL-AGENT v{VERSION} · Lokales Gateway', app)
app = re.sub(r"const current=updateStatus\?\.current_version\|\|'[0-9]+\.[0-9]+\.[0-9]+';", f"const current=updateStatus?.current_version||'{VERSION}';", app)

helpers = r'''function brainActivityRow(event){
  const when=event.at?new Date(event.at).toLocaleString():'';
  if(event.kind==='cycle'){
    const skipped=event.skipped==='agent_disabled'?'Agent pausiert':event.skipped==='outside_schedule'?'Außerhalb des Zeitplans':'';
    const title=skipped||'Agentenlauf';
    const detail=skipped?`${event.pending_after??event.pending_before??0} Mails warten`:`${event.processed||0} verarbeitet · ${event.drafts||0} Entwürfe · ${event.approvals||0} Freigaben · ${event.errors||0} Fehler · ${event.pending_after||0} warten`;
    return `<div class="setting-row"><span>${esc(when)} · ${esc(title)}</span><b>${esc(detail)}</b></div>`;
  }
  if(event.kind==='analysis') return `<div class="setting-row"><span>${esc(when)} · ${esc(event.subject||'(ohne Betreff)')}</span><b>${esc(event.priority||'normal')} · ${esc(event.category||'other')} · ${esc(event.action||'analysis')}</b></div>`;
  if(event.kind==='owner_feedback') return `<div class="setting-row"><span>${esc(when)} · Besitzer-Korrektur</span><b>${event.length_signal?`Stil: ${esc(event.length_signal)}`:event.subject_changed?'Betreff geändert':'Entwurf angepasst'}</b></div>`;
  if(event.kind==='learning_accepted') return `<div class="setting-row"><span>${esc(when)} · Gelernt</span><b>${esc(event.title||'Präferenz übernommen')}</b></div>`;
  if(event.kind==='learning_rejected') return `<div class="setting-row"><span>${esc(when)} · Lernvorschlag verworfen</span><b>${esc(event.title||'')}</b></div>`;
  return `<div class="setting-row"><span>${esc(when)} · ${esc(event.kind||'Aktivität')}</span><b>${esc(event.action||'')}</b></div>`;
}
function brainLearningCard(item){return `<div class="security-block"><span>${icon('spark',22)}</span><div><b>${esc(item.title||'Lernvorschlag')}</b><p>${esc(item.reason||'')}</p><small>${esc(item.memory_line||'')}</small><div class="inline-actions left"><button class="btn secondary compact" data-learning-reject="${esc(item.candidate_id)}">Verwerfen</button><button class="btn primary compact" data-learning-accept="${esc(item.candidate_id)}">Übernehmen</button></div></div></div>`;}
'''
app = replace_once(app, "function renderAgentSettings(){", helpers + "function renderAgentSettings(){", "brain UI helpers")

app = replace_once(
    app,
    "  const ruleRows=(behavior.rules||[]).map(ruleRow).join('');\n  return `<div class=\"settings-grid agent-settings-grid\">",
    r'''  const ruleRows=(behavior.rules||[]).map(ruleRow).join('');
  const brain=brainStatus||{};
  const brainInfo=brain.status||rs.brain||{};
  const brainMailboxes=brain.mailboxes||[];
  const pendingTotal=brain.pending_total??brainMailboxes.reduce((sum,item)=>sum+Number(item.pending||0),0);
  const activeBrainMailbox=brainMailboxes[0]||{};
  const runtimeLabel=activeBrainMailbox.state==='paused'?'Agent pausiert':activeBrainMailbox.state==='outside_schedule'?'Außerhalb des Zeitplans':activeBrainMailbox.state==='work_pending'?`${pendingTotal} Mails warten auf Analyse`:brainMailboxes.length?'Keine unbearbeiteten Mails':'Noch kein Postfachstatus';
  const runtimeDetail=activeBrainMailbox.state==='work_pending'?`Pro Zyklus bearbeitet der Agent bis zu ${activeBrainMailbox.max_messages_per_cycle||behavior.max_messages_per_cycle||20} Mails mit ${esc(activeBrainMailbox.provider||provider)} / ${esc(activeBrainMailbox.model||model)}.`:activeBrainMailbox.state==='outside_schedule'?`Der Agent arbeitet innerhalb ${esc(behavior.active_from||'00:00')}–${esc(behavior.active_until||'23:59')}.`:'Jeder Lauf wird lokal protokolliert; Fehler und Skip-Gründe bleiben sichtbar.';
  const learning=(brain.learning_candidates||[]).map(brainLearningCard).join('');
  const activity=(brain.recent_activity||[]).slice(0,10).map(brainActivityRow).join('');
  const brainPanels=`<section class="panel"><div class="panel-head"><div><span>AGENTEN-GEHIRN</span><h3>SOUL & Langzeitgedächtnis</h3></div><span class="badge soft">LOCAL</span></div><div class="setting-row"><span>Bekannte Kontakte</span><b>${esc(brainInfo.known_contacts||0)}</b></div><div class="setting-row"><span>Journal-Einträge</span><b>${esc(brainInfo.journal_events||0)}</b></div><div class="setting-row"><span>Besitzer-Korrekturen</span><b>${esc(brainInfo.feedback_events||0)}</b></div><label class="field"><span>SOUL.md · Identität & Arbeitsprinzipien</span><textarea id="brain-soul" rows="11">${esc(brain.soul||'')}</textarea></label><label class="field"><span>MEMORY.md · dauerhaftes Besitzerwissen</span><textarea id="brain-memory" rows="11">${esc(brain.memory||'')}</textarea></label><div class="security-note">${icon('shield',18)}<span>SOUL und MEMORY beeinflussen das LLM, können aber niemals Policy Engine, Freigaben oder die verpflichtende Agent-ID-Signatur überschreiben.</span></div><div class="inline-actions left"><button class="btn primary" id="settings-save-brain">Gehirn speichern</button><button class="btn secondary" id="settings-refresh-brain">Neu laden</button></div></section><section class="panel"><div class="panel-head"><div><span>AKTIVITÄT & LERNEN</span><h3>Was der Agent gerade tut</h3></div><span class="badge ${pendingTotal?'':'soft'}">${esc(pendingTotal)} WARTEN</span></div><div class="security-block">${icon('spark',22)}<div><b>${esc(runtimeLabel)}</b><p>${runtimeDetail}</p></div></div><div class="inline-actions left"><button class="btn primary" id="brain-run-agent">Agent jetzt arbeiten lassen</button><button class="btn secondary" id="brain-refresh-activity">Aktualisieren</button></div><div class="panel-head"><div><span>LERNVORSCHLÄGE</span><h3>Nur nach deiner Bestätigung</h3></div><span class="badge soft">${esc((brain.learning_candidates||[]).length)}</span></div>${learning||'<div class="empty-state">Noch keine stabilen Muster aus deinen Korrekturen erkannt.</div>'}<div class="panel-head"><div><span>LETZTE AKTIVITÄT</span><h3>Agenten-Journal</h3></div></div>${activity||'<div class="empty-state">Noch keine Agentenaktivität protokolliert.</div>'}</section>`;
  return `<div class="settings-grid agent-settings-grid">''',
    "brain panel variables",
)
app = replace_once(
    app,
    '    <section class="panel"><div class="panel-head"><div><span>LLM</span>',
    '    ${brainPanels}\n    <section class="panel"><div class="panel-head"><div><span>LLM</span>',
    "brain panels insertion",
)

brain_functions = r'''async function loadBrainStatus(silent=false){
  if(brainLoading)return;
  brainLoading=true;
  try{brainStatus=await get('/v1/agent/brain');}
  catch(e){if(!silent)showNotice(e.message,'error');}
  finally{brainLoading=false;}
}
async function saveBrainSettings(){
  const soul=document.getElementById('brain-soul')?.value??brainStatus?.soul??'';
  const memory=document.getElementById('brain-memory')?.value??brainStatus?.memory??'';
  try{brainStatus=await put('/v1/agent/brain',{soul,memory,actor:'local-user'});showNotice('Agenten-Gehirn gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
async function decideBrainLearning(id,decision){
  try{brainStatus=await post(`/v1/agent/brain/learning/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});showNotice(decision==='accept'?'Präferenz in MEMORY.md übernommen.':'Lernvorschlag verworfen.');render();}
  catch(e){showNotice(e.message,'error');}
}
'''
app = replace_once(app, "async function probeSettingsProvider(){", brain_functions + "async function probeSettingsProvider(){", "brain API functions")

app = replace_once(
    app,
    "  document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(activeView==='settings'&&!runtimeSettings)await loadRuntimeSettings(true);render();});",
    "  document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(activeView==='settings')await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true)]);render();});",
    "settings navigation brain load",
)
app = replace_once(
    app,
    "  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);",
    "  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);\n  document.getElementById('brain-run-agent')?.addEventListener('click',runAgentNow);\n  document.getElementById('settings-save-brain')?.addEventListener('click',saveBrainSettings);\n  document.getElementById('settings-refresh-brain')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});\n  document.getElementById('brain-refresh-activity')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});\n  document.querySelectorAll('[data-learning-accept]').forEach(el=>el.onclick=()=>decideBrainLearning(el.dataset.learningAccept,'accept'));\n  document.querySelectorAll('[data-learning-reject]').forEach(el=>el.onclick=()=>decideBrainLearning(el.dataset.learningReject,'reject'));",
    "brain bindings",
)

app = regex_once(
    app,
    r"async function runAgentNow\(\)\{.*?\n\}",
    r'''async function runAgentNow(){
  const mailbox=dashboard.mailboxes[0];
  try{
    const result=await post('/v1/agent/run',{mailbox_id:mailbox?.mailbox_id||null,force:true});
    await Promise.all([loadDashboard(true),loadBrainStatus(true)]);
    const cycles=result.results||[];
    const total=key=>cycles.reduce((sum,item)=>sum+Number(item[key]||0),0);
    const pending=cycles.reduce((sum,item)=>sum+Number(item.pending_after||0),0);
    showNotice(`Agentenlauf · ${total('processed')} verarbeitet · ${total('drafts')} Entwürfe · ${total('approvals')} Freigaben · ${total('errors')} Fehler · ${pending} warten`);
    render();
  }catch(e){showNotice(e.message,'error');}
}''',
    "runAgentNow",
    flags=re.S,
)
app = replace_once(
    app,
    "async function syncNow(){const mb=dashboard.mailboxes[0];if(!mb)return;busy=true;render();try{await post('/v1/sync/run',{mailbox_id:mb.mailbox_id,limit:100});await loadDashboard(true);showNotice('Postfach ist aktuell.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}",
    "async function syncNow(){const mb=dashboard.mailboxes[0];if(!mb)return;busy=true;render();try{await post('/v1/sync/run',{mailbox_id:mb.mailbox_id,limit:100});await Promise.all([loadDashboard(true),loadBrainStatus(true)]);showNotice('Postfach ist aktuell. Agentenstatus wurde aktualisiert.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}",
    "sync brain refresh",
)
app = replace_once(
    app,
    "try{await put(`/v1/drafts/${encodeURIComponent(id)}`,{subject,body,recipient,actor:'local-user'});editingDraftId=null;await loadDashboard(true);showNotice('Entwurf gespeichert und kryptografisch neu signiert.');render();}",
    "try{await put(`/v1/drafts/${encodeURIComponent(id)}`,{subject,body,recipient,actor:'local-user'});editingDraftId=null;await Promise.all([loadDashboard(true),loadBrainStatus(true)]);showNotice('Entwurf gespeichert, neu signiert und als Besitzer-Feedback berücksichtigt.');render();}",
    "draft feedback refresh",
)
app = replace_once(
    app,
    "if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true)]);",
    "if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true),loadBrainStatus(true)]);",
    "boot brain load",
)
app_path.write_text(app, encoding="utf-8")
