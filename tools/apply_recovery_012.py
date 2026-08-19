from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected marker missing in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Startup recovery must claim every execution left behind by a previous process immediately.
replace_once(
    "apps/gateway/mail_agent_gateway/recovery.py",
    "def recover_stale_executions(self, *, max_age_seconds: int = 300) -> dict[str, int]:\n        cutoff = (datetime.now(UTC) - timedelta(seconds=max(30, max_age_seconds))).isoformat()",
    "def recover_stale_executions(self, *, max_age_seconds: int = 0) -> dict[str, int]:\n        cutoff = (datetime.now(UTC) - timedelta(seconds=max(0, max_age_seconds))).isoformat()",
)

# Gateway wiring.
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "from .registry_client import RegistryClient\n",
    "from .recovery import RecoveryManager\nfrom .registry_client import RegistryClient\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "    RegistrationResponse,\n    RuleSimulationRequest,\n",
    "    RegistrationResponse,\n    RecoveryReconcileRequest,\n    RuleSimulationRequest,\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "draft_service = DraftService(\n    mail_store=mail_store,\n    identity_manager=identity_manager,\n    state_store=state_store,\n    policy_engine=policy_engine,\n    audit_log=audit_log,\n    brain=agent_runtime.brain,\n)\n",
    "draft_service = DraftService(\n    mail_store=mail_store,\n    identity_manager=identity_manager,\n    state_store=state_store,\n    policy_engine=policy_engine,\n    audit_log=audit_log,\n    brain=agent_runtime.brain,\n)\nrecovery_manager = RecoveryManager(\n    data_dir=settings.data_dir,\n    mail_store=mail_store,\n    identity_manager=identity_manager,\n    state_store=state_store,\n    vault=vault,\n    providers=providers,\n    mailbox_supplier=_configured_mailboxes,\n)\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "async def lifespan(_: FastAPI):\n    task: asyncio.Task | None = None\n    _sync_stop.clear()\n",
    "async def lifespan(_: FastAPI):\n    task: asyncio.Task | None = None\n    recovered = recovery_manager.recover_stale_executions()\n    if recovered['outbound_uncertain'] or recovered['retryable_failed']:\n        audit_log.append('startup_execution_recovery', details=recovered)\n    _sync_stop.clear()\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "@app.get(\"/v1/onboarding/status\")\n",
    "@app.get(\"/v1/system/health\")\nasync def system_health() -> dict:\n    return await recovery_manager.report()\n\n\n@app.post(\"/v1/system/recovery/approvals/{approval_id}/reconcile\")\nasync def reconcile_uncertain_approval(\n    approval_id: str, body: RecoveryReconcileRequest\n) -> dict:\n    try:\n        approval = recovery_manager.reconcile_uncertain(approval_id, outcome=body.outcome)\n    except KeyError as exc:\n        raise HTTPException(status_code=404, detail=\"Approval not found\") from exc\n    except (RuntimeError, ValueError) as exc:\n        raise HTTPException(status_code=409, detail=str(exc)) from exc\n    audit_log.append(\n        \"uncertain_outbound_reconciled\",\n        actor=body.actor,\n        details={\n            \"approval_id\": approval_id,\n            \"outcome\": body.outcome,\n            \"action\": approval.get(\"action\"),\n        },\n    )\n    return approval\n\n\n@app.get(\"/v1/onboarding/status\")\n",
)
replace_once(
    "apps/gateway/mail_agent_gateway/main.py",
    "        failed = [item for item in mail_store.list_approvals(\"approved\", limit) if item.get(\"execution_status\") == \"failed\"]\n        combined = sorted(pending + failed, key=lambda item: item.get(\"created_at\") or \"\", reverse=True)\n",
    "        recoverable = [\n            item\n            for item in mail_store.list_approvals(\"approved\", limit)\n            if item.get(\"execution_status\") in {\"failed\", \"uncertain\", \"ready\"}\n        ]\n        combined = sorted(\n            pending + recoverable,\n            key=lambda item: item.get(\"created_at\") or \"\",\n            reverse=True,\n        )\n",
)

# Version synchronization.
for path, old, new in [
    ("pyproject.toml", 'version = "0.11.0"', 'version = "0.12.0"'),
    ("apps/gateway/mail_agent_gateway/main.py", 'APP_VERSION = "0.11.0"', 'APP_VERSION = "0.12.0"'),
    ("apps/launcher/mail_agent_launcher/main.py", 'APP_VERSION = "0.11.0"', 'APP_VERSION = "0.12.0"'),
    ("packages/agent_core/mail_agent_core/identity.py", 'app_version: str = "0.11.0"', 'app_version: str = "0.12.0"'),
    ("packaging/windows/MailAgent.iss", '#define MyAppVersion "0.11.0"', '#define MyAppVersion "0.12.0"'),
]:
    replace_once(path, old, new)

# UI state + version.
replace_once(
    "apps/web/app.js",
    "let ruleSimulation = null;\nlet settingsProbe = null;",
    "let ruleSimulation = null;\nlet systemHealth = null;\nlet systemHealthLoading = false;\nlet settingsProbe = null;",
)
replace_once(
    "apps/web/app.js",
    "MAIL-AGENT v0.11.0 · Lokales Gateway",
    "MAIL-AGENT v0.12.0 · Lokales Gateway",
)
replace_once(
    "apps/web/app.js",
    "const configured=document.getElementById('google-connect')?.dataset.configured==='1';",
    "const configured=document.getElementById('google-connect')?.dataset.configured==='1'||!!oauthProviders.google?.configured;",
)
replace_once(
    "apps/web/app.js",
    "const configured=document.getElementById('microsoft-connect')?.dataset.configured==='1';",
    "const configured=document.getElementById('microsoft-connect')?.dataset.configured==='1'||!!oauthProviders.microsoft?.configured;",
)
replace_once(
    "apps/web/app.js",
    "${navItem('shadow','Testmodus','shield',runtimeSettings?.behavior?.execution_mode==='shadow'?'SHADOW':'')}${navItem('inbox'",
    "${navItem('shadow','Testmodus','shield',runtimeSettings?.behavior?.execution_mode==='shadow'?'SHADOW':'')}${navItem('system','System','settings',systemHealth?.summary?.error||systemHealth?.summary?.warning||'')}${navItem('inbox'",
)
replace_once(
    "apps/web/app.js",
    "function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',shadow:'Shadow Test',inbox:'Inbox'",
    "function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',shadow:'Shadow Test',system:'Systemzustand',inbox:'Inbox'",
)
replace_once(
    "apps/web/app.js",
    "  if(activeView==='shadow') content=renderShadowCenter();\n  if(activeView==='inbox')",
    "  if(activeView==='shadow') content=renderShadowCenter();\n  if(activeView==='system') content=renderSystemHealth();\n  if(activeView==='inbox')",
)
replace_once(
    "apps/web/app.js",
    "function approvalCard(item){const p=item.proposal||{};const failed=item.status==='approved'&&item.execution_status==='failed';const sends=['send_reply','forward'].includes(item.action);const status=failed?`<span class=\"delivery-failed\">Ausführung fehlgeschlagen · ${esc(item.execution_error||'erneut versuchen')}</span>`:`<span>Risiko: ${esc(item.policy?.risk||'')}</span>`;const retryLabel=sends?'Erneut senden':'Erneut ausführen';const approveLabel=sends?'Freigeben & senden':'Freigeben & ausführen';const actions=failed?`<button class=\"btn primary compact\" data-execute=\"${esc(item.approval_id)}\">${icon('sync',15)} ${retryLabel}</button>`:`<button class=\"btn secondary compact\" data-reject=\"${esc(item.approval_id)}\">${icon('x',15)} Ablehnen</button><button class=\"btn primary compact\" data-approve=\"${esc(item.approval_id)}\">${icon('check',15)} ${approveLabel}</button>`;return `<article class=\"approval\"><span class=\"risk-icon\">${icon('shield',19)}</span><div class=\"approval-copy\"><div class=\"mail-line\"><b>${esc(item.action)}</b>${status}</div><h4>${esc(p.subject||p.destination_folder||p.recipient||'Mail-Aktion')}</h4><p>${esc(p.summary||p.reason||item.policy?.reason||'')}</p></div><div class=\"approval-actions\">${actions}</div></article>`;}",
    "function approvalCard(item){const p=item.proposal||{};const execution=item.execution_status||'';const failed=item.status==='approved'&&execution==='failed';const uncertain=item.status==='approved'&&execution==='uncertain';const ready=item.status==='approved'&&execution==='ready';const sends=['send_reply','forward'].includes(item.action);const status=uncertain?`<span class=\"delivery-failed\">Versandstatus unklar · ${esc(item.execution_error||'Gesendet-Ordner prüfen')}</span>`:failed?`<span class=\"delivery-failed\">Ausführung fehlgeschlagen · ${esc(item.execution_error||'erneut versuchen')}</span>`:ready?'<span>Erneuter Versuch freigegeben</span>':`<span>Risiko: ${esc(item.policy?.risk||'')}</span>`;const retryLabel=sends?'Erneut senden':'Erneut ausführen';const approveLabel=sends?'Freigeben & senden':'Freigeben & ausführen';let actions='';if(uncertain)actions=`<button class=\"btn secondary compact\" data-reconcile-sent=\"${esc(item.approval_id)}\">${icon('check',15)} Bereits gesendet</button><button class=\"btn primary compact\" data-reconcile-retry=\"${esc(item.approval_id)}\">${icon('sync',15)} Nicht gesendet</button>`;else if(failed||ready)actions=`<button class=\"btn primary compact\" data-execute=\"${esc(item.approval_id)}\">${icon('sync',15)} ${retryLabel}</button>`;else actions=`<button class=\"btn secondary compact\" data-reject=\"${esc(item.approval_id)}\">${icon('x',15)} Ablehnen</button><button class=\"btn primary compact\" data-approve=\"${esc(item.approval_id)}\">${icon('check',15)} ${approveLabel}</button>`;return `<article class=\"approval\"><span class=\"risk-icon\">${icon('shield',19)}</span><div class=\"approval-copy\"><div class=\"mail-line\"><b>${esc(item.action)}</b>${status}</div><h4>${esc(p.subject||p.destination_folder||p.recipient||'Mail-Aktion')}</h4><p>${uncertain?'MAIL-AGENT wurde während der Ausführung beendet. Prüfe zuerst den Gesendet-Ordner; ein automatischer Retry könnte die Mail doppelt senden.':esc(p.summary||p.reason||item.policy?.reason||'')}</p></div><div class=\"approval-actions\">${actions}</div></article>`;}",
)

# Add System Health rendering before brainLearningCard.
replace_once(
    "apps/web/app.js",
    "function brainLearningCard(item){",
    """function healthStatusLabel(value){return ({ok:'Bereit',warning:'Warnung',error:'Aktion nötig'})[value]||value||'Unbekannt';}
function healthActionButton(check){
  if(!check.action)return '';
  const labels={retry_sync:'Sync erneut versuchen',open_llm_settings:'LLM-Einstellungen öffnen',open_approvals:'Freigaben öffnen',review_uncertain:'Versandstatus prüfen',reconnect_mailbox:'Postfach neu verbinden',open_mailbox_setup:'Postfach einrichten',open_logs:'Diagnose anzeigen',restart_onboarding:'Einrichtung prüfen'};
  return `<button class=\"btn secondary compact\" data-health-action=\"${esc(check.action)}\" data-health-mailbox=\"${esc(check.data?.mailbox_id||'')}\">${esc(labels[check.action]||'Öffnen')}</button>`;
}
function renderSystemHealth(){
  const health=systemHealth||{};
  const summary=health.summary||{};
  const checks=health.checks||[];
  const overall=health.overall||'checking';
  const headline=overall==='ok'?'Alles bereit':overall==='degraded'?'System läuft mit Hinweisen':'Aktion erforderlich';
  const detail=overall==='ok'?'Gateway, lokaler Speicher, Datenbank, Agentenidentität, Postfach und LLM sind bereit.':overall==='degraded'?'MAIL-AGENT läuft weiter, aber mindestens ein Bereich sollte geprüft werden.':'Mindestens ein Problem braucht deine Entscheidung oder erneute Verbindung.';
  return `<div class=\"system-center\"><section class=\"panel activity-hero\"><div><span class=\"hero-kicker\">RELIABILITY & RECOVERY</span><h2>${esc(headline)}</h2><p>${esc(detail)}</p><div class=\"hero-actions\"><button class=\"btn primary\" id=\"system-health-refresh\" ${systemHealthLoading?'disabled':''}>${systemHealthLoading?'Prüfe …':'System prüfen'}</button></div></div><div class=\"hero-orb\">${icon(overall==='ok'?'check':'shield',34)}</div></section><div class=\"stats-grid\">${metric('Bereit',summary.ok||0,'erfolgreiche Prüfungen','check')}${metric('Warnungen',summary.warning||0,'weiterhin funktionsfähig','sync')}${metric('Fehler',summary.error||0,'brauchen Aufmerksamkeit','shield')}${metric('Geprüft',health.checked_at?new Date(health.checked_at).toLocaleTimeString():'—','lokale Selbstdiagnose','settings')}</div><section class=\"panel full\"><div class=\"panel-head\"><div><span>SELBSTDIAGNOSE</span><h3>Komponenten & Recovery</h3></div><span class=\"badge ${overall==='ok'?'soft':''}\">${esc(overall.toUpperCase())}</span></div>${checks.length?checks.map(check=>`<div class=\"security-block health-check ${esc(check.status||'')}\"><span>${icon(check.status==='ok'?'check':check.status==='warning'?'sync':'shield',22)}</span><div><b>${esc(check.id||'Prüfung')} · ${esc(healthStatusLabel(check.status))}</b><p>${esc(check.detail||'')}</p>${healthActionButton(check)}</div></div>`).join(''):emptyState('settings','Noch nicht geprüft','Starte die lokale Selbstdiagnose.')}</section><section class=\"panel full\"><div class=\"security-note\">${icon('shield',18)}<span>Nach einem Absturz während Send/Forward versucht MAIL-AGENT niemals automatisch erneut zu senden. Ein unklarer Versandstatus muss zuerst von dir abgeglichen werden.</span></div></section></div>`;
}
async function loadSystemHealth(silent=false){
  if(systemHealthLoading)return;
  systemHealthLoading=true;
  try{systemHealth=await get('/v1/system/health');}
  catch(e){if(!silent)showNotice(e.message,'error');}
  finally{systemHealthLoading=false;}
}
async function handleHealthAction(action,mailboxId){
  if(action==='retry_sync'){
    try{await post('/v1/sync/run',{mailbox_id:mailboxId||null,limit:100});await Promise.all([loadDashboard(true),loadSystemHealth(true)]);showNotice('Synchronisierung erneut ausgeführt.');render();}catch(e){showNotice(e.message,'error');}
    return;
  }
  if(action==='open_llm_settings'){activeView='settings';await loadRuntimeSettings(true);render();return;}
  if(['open_approvals','review_uncertain'].includes(action)){activeView='approvals';await loadDashboard(true);render();return;}
  if(action==='reconnect_mailbox'){
    const mailbox=dashboard.mailboxes.find(item=>item.mailbox_id===mailboxId)||dashboard.mailboxes[0];
    if(!mailbox){showNotice('Postfach nicht gefunden.','error');return;}
    form.emailAddress=mailbox.email_address||form.emailAddress;
    if(mailbox.connector==='gmail_api')await connectGoogle();
    else if(mailbox.connector==='microsoft_graph')await connectMicrosoft();
    else {showNotice('Für ein manuelles IMAP-Postfach müssen die Zugangsdaten im Postfach-Setup erneut eingegeben werden.','error');return;}
    await Promise.all([loadDashboard(true),loadSystemHealth(true)]);render();return;
  }
  if(action==='open_mailbox_setup'){showNotice('Postfachverbindung ist noch nicht eingerichtet.');return;}
  showNotice('Der Diagnosehinweis wurde protokolliert. Weitere Details stehen im lokalen MAIL-AGENT-Log.');
}
async function reconcileApproval(id,outcome){
  try{
    const result=await post(`/v1/system/recovery/approvals/${encodeURIComponent(id)}/reconcile`,{outcome,actor:'local-user'});
    await Promise.all([loadDashboard(true),loadSystemHealth(true)]);
    showNotice(outcome==='already_sent'?'Als bereits gesendet bestätigt. Es wird nichts erneut versendet.':'Als nicht gesendet markiert. Ein erneuter Versand ist jetzt separat möglich.');
    render();
  }catch(e){showNotice(e.message,'error');}
}

function brainLearningCard(item){""",
)
replace_once(
    "apps/web/app.js",
    "const current=updateStatus?.current_version||'0.10.0';",
    "const current=updateStatus?.current_version||'0.12.0';",
)
replace_once(
    "apps/web/app.js",
    "if(['settings','activity','shadow'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true),activeView==='shadow'?loadShadowStatus(true):Promise.resolve()]);render();",
    "if(['settings','activity','shadow','system'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true),activeView==='shadow'?loadShadowStatus(true):Promise.resolve(),activeView==='system'?loadSystemHealth(true):Promise.resolve()]);render();",
)
replace_once(
    "apps/web/app.js",
    "  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));\n",
    "  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));\n  document.querySelectorAll('[data-reconcile-sent]').forEach(el=>el.onclick=()=>reconcileApproval(el.dataset.reconcileSent,'already_sent'));\n  document.querySelectorAll('[data-reconcile-retry]').forEach(el=>el.onclick=()=>reconcileApproval(el.dataset.reconcileRetry,'retry'));\n  document.getElementById('system-health-refresh')?.addEventListener('click',async()=>{await loadSystemHealth(false);render();});\n  document.querySelectorAll('[data-health-action]').forEach(el=>el.onclick=()=>handleHealthAction(el.dataset.healthAction,el.dataset.healthMailbox));\n",
)
replace_once(
    "apps/web/app.js",
    "if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true),loadBrainStatus(true)]);",
    "if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true),loadBrainStatus(true),loadSystemHealth(true)]);",
)

print("MAIL-AGENT 0.12.0 Reliability & Recovery integration applied.")
