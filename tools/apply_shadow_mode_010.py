from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Marker not found for {label}")
    if text.count(old) != 1:
        raise RuntimeError(f"Marker for {label} is not unique: {text.count(old)}")
    return text.replace(old, new, 1)


def patch_mail_store() -> None:
    path = Path("apps/gateway/mail_agent_gateway/mail_store.py")
    text = path.read_text(encoding="utf-8")
    old = '''                CREATE INDEX IF NOT EXISTS idx_agent_processing_time
                    ON agent_processing(mailbox_id, processed_at DESC);
                """
'''
    new = '''                CREATE INDEX IF NOT EXISTS idx_agent_processing_time
                    ON agent_processing(mailbox_id, processed_at DESC);

                CREATE TABLE IF NOT EXISTS agent_shadow_processing (
                    mailbox_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    proposal_action TEXT,
                    confidence REAL,
                    processed_at TEXT NOT NULL,
                    error TEXT,
                    PRIMARY KEY (mailbox_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_shadow_processing_time
                    ON agent_shadow_processing(mailbox_id, processed_at DESC);
                """
'''
    text = replace_once(text, old, new, "shadow processing table")
    old = '''    def enqueue_approval(
        self,
        proposal: MailActionProposal,
'''
    new = '''    def is_shadow_processed(self, mailbox_id: str, message_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM agent_shadow_processing WHERE mailbox_id=? AND message_id=?",
                (mailbox_id, message_id),
            ).fetchone()
        if row is None:
            return False
        return row["status"] != "error"

    def record_shadow_processing(
        self,
        mailbox_id: str,
        message_id: str,
        *,
        status: str,
        proposal_action: str | None = None,
        confidence: float | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_shadow_processing (
                    mailbox_id, message_id, status, proposal_action, confidence, processed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mailbox_id, message_id) DO UPDATE SET
                    status=excluded.status,
                    proposal_action=excluded.proposal_action,
                    confidence=excluded.confidence,
                    processed_at=excluded.processed_at,
                    error=excluded.error
                """,
                (
                    mailbox_id,
                    message_id,
                    status,
                    proposal_action,
                    confidence,
                    utc_now(),
                    error,
                ),
            )

    def enqueue_approval(
        self,
        proposal: MailActionProposal,
'''
    text = replace_once(text, old, new, "shadow processing methods")
    path.write_text(text, encoding="utf-8")


def patch_activity() -> None:
    path = Path("packages/agent_core/mail_agent_core/activity.py")
    text = path.read_text(encoding="utf-8")
    old = '''    "artifact",
    "outcome",
}
'''
    new = '''    "artifact",
    "outcome",
    "execution_mode",
    "shadow_run_id",
    "planned_artifacts",
    "side_effects",
    "matched_rule",
}
'''
    text = replace_once(text, old, new, "activity safe fields")
    old = '''            if value is None or isinstance(value, (bool, int, float)):
                result[key_text] = value
            else:
                result[key_text] = _safe_text(value, 500)
'''
    new = '''            if value is None or isinstance(value, (bool, int, float)):
                result[key_text] = value
            elif isinstance(value, (list, tuple)):
                result[key_text] = [_safe_text(item, 96) for item in list(value)[:8]]
            else:
                result[key_text] = _safe_text(value, 500)
'''
    text = replace_once(text, old, new, "activity list sanitizer")
    path.write_text(text, encoding="utf-8")


def patch_main() -> None:
    path = Path("apps/gateway/mail_agent_gateway/main.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "import time\n", "import time\nimport uuid\n", "uuid import")
    old = '''    ProviderProbeRequest,
    RegistrationResponse,
    SyncRunRequest,
)
'''
    new = '''    ProviderProbeRequest,
    RegistrationResponse,
    RuleSimulationRequest,
    ShadowReplayRequest,
    SyncRunRequest,
)
'''
    text = replace_once(text, old, new, "shadow schema imports")
    text = replace_once(
        text,
        '_sync_stop = asyncio.Event()\n',
        '_sync_stop = asyncio.Event()\n_shadow_jobs: dict[str, dict] = {}\n',
        "shadow jobs state",
    )
    text = text.replace('APP_VERSION = "0.9.0"', 'APP_VERSION = "0.10.0"')
    old = '''        "invariants": {
            "agent_identity_required": True,
'''
    new = '''        "invariants": {
            "agent_identity_required": True,
            "shadow_side_effects_forbidden": True,
            "shadow_uses_separate_processing_queue": True,
'''
    text = replace_once(text, old, new, "settings invariants")
    old = '''@app.get("/v1/agent/activity")
async def get_agent_activity(limit: int = 50, mailbox_id: str | None = None) -> dict:
    _configuration_or_409()
    return {
        "traces": agent_runtime.activity.recent_traces(limit, mailbox_id=mailbox_id),
        "summary": agent_runtime.activity.summary(mailbox_id=mailbox_id),
    }


@app.put("/v1/agent/brain")
'''
    new = '''@app.get("/v1/agent/activity")
async def get_agent_activity(limit: int = 50, mailbox_id: str | None = None) -> dict:
    _configuration_or_409()
    return {
        "traces": agent_runtime.activity.recent_traces(limit, mailbox_id=mailbox_id),
        "summary": agent_runtime.activity.summary(mailbox_id=mailbox_id),
    }


def _public_shadow_job(job: dict) -> dict:
    return {
        key: value
        for key, value in job.items()
        if not key.startswith("_")
    }


def _shadow_payload() -> dict:
    _state, config = _configuration_or_409()
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    mailboxes = []
    for mailbox in _configured_mailboxes():
        mailbox_id = str(mailbox.get("mailbox_id") or "")
        if not mailbox_id:
            continue
        status = agent_runtime.mailbox_status(mailbox_id)
        status["email_address"] = mailbox.get("email_address")
        mailboxes.append(status)
    jobs = sorted(
        (_public_shadow_job(item) for item in _shadow_jobs.values()),
        key=lambda item: str(item.get("started_at") or ""),
        reverse=True,
    )[:20]
    return {
        "execution_mode": behavior.execution_mode.value,
        "side_effects_allowed": False,
        "mailboxes": mailboxes,
        "jobs": jobs,
        "reports": agent_runtime.shadow_reports.recent_reports(10),
    }


async def _run_shadow_replay_job(job_id: str, mailbox_id: str, limit: int) -> None:
    job = _shadow_jobs[job_id]
    job["status"] = "running"

    def progress(done: int, total: int) -> None:
        job["completed"] = done
        job["total"] = total

    try:
        report = await agent_runtime.shadow_replay(
            mailbox_id,
            limit=limit,
            progress=progress,
        )
        job["status"] = "completed"
        job["completed"] = report.get("analyzed", 0) + report.get("errors", 0)
        job["total"] = len(report.get("results") or [])
        job["report"] = report
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        audit_log.append(
            "agent_shadow_replay_failed",
            details={"job_id": job_id, "mailbox_id": mailbox_id, "error": str(exc)},
        )


@app.get("/v1/agent/shadow")
async def get_shadow_status() -> dict:
    return _shadow_payload()


@app.get("/v1/agent/shadow/jobs/{job_id}")
async def get_shadow_job(job_id: str) -> dict:
    _configuration_or_409()
    job = _shadow_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Shadow replay job not found")
    return _public_shadow_job(job)


@app.post("/v1/agent/shadow/replay")
async def start_shadow_replay(body: ShadowReplayRequest) -> dict:
    _configuration_or_409()
    mailbox_id = body.mailbox_id
    if not mailbox_id:
        configured = _configured_mailboxes()
        if not configured:
            raise HTTPException(status_code=409, detail="No mailbox is configured")
        mailbox_id = configured[0]["mailbox_id"]
    try:
        _mailbox_by_id(mailbox_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown mailbox: {mailbox_id}") from exc
    active = next(
        (
            item
            for item in _shadow_jobs.values()
            if item.get("mailbox_id") == mailbox_id
            and item.get("status") in {"queued", "running"}
        ),
        None,
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="A Shadow replay is already running for this mailbox")
    job_id = "shadow_job_" + uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "mailbox_id": mailbox_id,
        "status": "queued",
        "requested": body.limit,
        "completed": 0,
        "total": body.limit,
        "started_at": datetime.now(UTC).isoformat(),
        "side_effects": 0,
    }
    _shadow_jobs[job_id] = job
    job["_task"] = asyncio.create_task(
        _run_shadow_replay_job(job_id, mailbox_id, body.limit),
        name=f"mail-agent-shadow-{job_id[-8:]}",
    )
    audit_log.append(
        "agent_shadow_replay_started",
        details={"job_id": job_id, "mailbox_id": mailbox_id, "limit": body.limit},
    )
    return _public_shadow_job(job)


@app.post("/v1/agent/rules/simulate")
async def simulate_agent_rule(body: RuleSimulationRequest) -> dict:
    _configuration_or_409()
    return agent_runtime.simulate_rule(
        sender=body.sender,
        action=body.action,
        confidence=body.confidence,
        priority=body.priority,
        category=body.category,
        needs_reply=body.needs_reply,
    )


@app.put("/v1/agent/brain")
'''
    text = replace_once(text, old, new, "shadow API endpoints")
    path.write_text(text, encoding="utf-8")


def patch_app() -> None:
    path = Path("apps/web/app.js")
    text = path.read_text(encoding="utf-8")
    old = '''let brainLoading = false;
let settingsProbe = null;
'''
    new = '''let brainLoading = false;
let shadowStatus = null;
let shadowLoading = false;
let ruleSimulation = null;
let settingsProbe = null;
'''
    text = replace_once(text, old, new, "shadow UI state")
    text = text.replace("MAIL-AGENT v0.9.0", "MAIL-AGENT v0.10.0")
    text = text.replace("||'0.9.0'", "||'0.10.0'")
    old = '''${navItem('overview','Übersicht','home')}${navItem('activity','Aktivität','spark',brainStatus?.pending_total||'')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}${navItem('approvals','Freigaben','shield',dashboard.approvals.length||'')}${navItem('drafts','Entwürfe','draft',dashboard.drafts.length||'')}${navItem('settings','Einstellungen','settings')}'''
    new = '''${navItem('overview','Übersicht','home')}${navItem('activity','Aktivität','spark',brainStatus?.pending_total||'')}${navItem('shadow','Testmodus','shield',runtimeSettings?.behavior?.execution_mode==='shadow'?'SHADOW':'')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}${navItem('approvals','Freigaben','shield',dashboard.approvals.length||'')}${navItem('drafts','Entwürfe','draft',dashboard.drafts.length||'')}${navItem('settings','Einstellungen','settings')}'''
    text = replace_once(text, old, new, "shadow navigation")
    old = "function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}"
    new = "function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',shadow:'Shadow Test',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}"
    text = replace_once(text, old, new, "shadow view title")
    old = '''  if(activeView==='activity') content=renderActivityCenter();
  if(activeView==='inbox') content=`'''
    new = '''  if(activeView==='activity') content=renderActivityCenter();
  if(activeView==='shadow') content=renderShadowCenter();
  if(activeView==='inbox') content=`'''
    text = replace_once(text, old, new, "shadow view render")
    old = '''function brainLearningCard(item){return `<div class="security-block">'''
    shadow_ui = r'''function shadowOutcomeLabel(value=''){
  return ({would_draft:'Entwurf',would_approval:'Freigabe',would_execute:'Ausführung',no_action:'Keine Aktion',ignored:'Ignoriert',below_confidence:'Zu unsicher',blocked:'Blockiert',error:'Fehler'})[value]||value||'—';
}
function shadowResultRow(item){
  const artifacts=(item.planned_artifacts||[]).join(', ')||'keine';
  return `<div class="shadow-result"><div><b>${esc(item.subject||'(ohne Betreff)')}</b><small>${esc(item.sender||'')} · ${esc(item.category||'other')} · ${esc(item.priority||'normal')}</small></div><span class="badge soft">${esc(shadowOutcomeLabel(item.simulated_outcome))}</span><p>${esc(item.reason||item.error||'')}</p><small>Geplant: ${esc(artifacts)} · Side Effects: 0</small></div>`;
}
function shadowReportCard(report){
  const outcomes=report.outcomes||{};
  return `<article class="shadow-report"><div class="panel-head"><div><span>${esc(report.finished_at?new Date(report.finished_at).toLocaleString():'')}</span><h3>${esc(report.analyzed||0)} analysiert · ${esc(report.errors||0)} Fehler</h3></div><span class="badge soft">0 SIDE EFFECTS</span></div><div class="shadow-outcomes">${Object.entries(outcomes).map(([key,value])=>`<span><b>${esc(value)}</b>${esc(shadowOutcomeLabel(key))}</span>`).join('')||'<span><b>0</b>Keine Ergebnisse</span>'}</div>${(report.results||[]).slice(0,25).map(shadowResultRow).join('')}</article>`;
}
function renderRuleSimulation(){
  if(!ruleSimulation)return '<div class="empty-state">Noch keine Regel simuliert.</div>';
  const matched=ruleSimulation.matched_rule;
  const policy=ruleSimulation.policy||{};
  return `<div class="rule-sim-result"><div class="setting-row"><span>Treffer</span><b>${matched?esc(matched.pattern):'Keine spezielle Regel'}</b></div><div class="setting-row"><span>Regelmodus</span><b>${esc(ruleSimulation.rule_mode||'normal')}</b></div><div class="setting-row"><span>LLM-Aktion → Gateway</span><b>${esc(ruleSimulation.original_action)} → ${esc(ruleSimulation.resulting_action)}</b></div><div class="setting-row"><span>Policy</span><b>${policy.allowed?'Erlaubt':'Blockiert'} · ${esc(policy.risk||'')}</b></div><div class="setting-row"><span>Geplant</span><b>${esc((ruleSimulation.planned_artifacts||[]).join(', ')||'keine Aktion')}</b></div><div class="security-note">${icon('shield',18)}<span>Simulation abgeschlossen: <b>0 Side Effects</b>. Keine Mail, kein Draft und keine Approval-Queue wurde verändert.</span></div></div>`;
}
function renderShadowCenter(){
  const status=shadowStatus||{};
  const behavior=runtimeSettings?.behavior||{};
  const mode=behavior.execution_mode||status.execution_mode||'live';
  const mailbox=status.mailboxes?.[0]||{};
  const running=(status.jobs||[]).find(job=>['queued','running'].includes(job.status));
  const reports=status.reports||[];
  const progress=running?Math.round((Number(running.completed||0)/Math.max(1,Number(running.total||running.requested||1)))*100):0;
  return `<div class="shadow-center">
    <section class="panel shadow-hero ${mode==='shadow'?'active':''}"><div><span class="hero-kicker">SAFE EVALUATION</span><h2>${mode==='shadow'?'Shadow Mode ist aktiv':'Live Mode ist aktiv'}</h2><p>${mode==='shadow'?'Neue Mails werden vollständig analysiert, aber Drafts, Approvals und Mailbox-Aktionen sind technisch gesperrt.':'Der Agent arbeitet produktiv innerhalb deiner Policy- und Freigaberegeln.'}</p><div class="hero-actions">${mode==='shadow'?'<button class="btn secondary" id="shadow-disable">Zurück zu Live</button>':'<button class="btn primary" id="shadow-enable">Shadow Mode aktivieren</button>'}<button class="btn secondary" id="shadow-refresh">Aktualisieren</button></div></div><div class="hero-orb">${icon('shield',34)}</div></section>
    <div class="stats-grid">${metric('Modus',mode==='shadow'?'SHADOW':'LIVE',mode==='shadow'?'0 produktive Side Effects':'Policy-gesteuerte Ausführung','shield')}${metric('Live-Backlog',mailbox.live_pending||0,'noch nicht produktiv verarbeitet','inbox')}${metric('Shadow-Backlog',mailbox.shadow_pending||0,'noch nicht simuliert','spark')}${metric('Reports',reports.length,'lokale Shadow-Auswertungen','draft')}</div>
    <div class="shadow-grid"><section class="panel"><div class="panel-head"><div><span>HISTORICAL REPLAY</span><h3>Echte Mails gefahrlos testen</h3></div><span class="badge soft">LLM CALLS</span></div><p class="rule-help">Replay liest bereits lokal synchronisierte Mails und führt dieselbe Brain → LLM → Rule → Policy-Kette aus. Es erzeugt niemals Drafts, Approvals oder Remote-Aktionen.</p><label class="field"><span>Anzahl Mails</span><select id="shadow-replay-limit"><option value="25">25 Mails</option><option value="100">100 Mails</option><option value="500">500 Mails</option></select></label>${running?`<div class="shadow-progress"><span style="width:${progress}%"></span></div><small>${esc(running.completed||0)} / ${esc(running.total||running.requested||0)} analysiert · ${esc(progress)} %</small>`:''}<div class="inline-actions left"><button class="btn primary" id="shadow-replay" ${running||shadowLoading?'disabled':''}>${running?'Replay läuft …':'Shadow-Test starten'}</button></div><div class="security-note">${icon('shield',18)}<span>Bei 500 Mails entstehen bis zu 500 LLM-Aufrufe. Standard ist deshalb bewusst 25.</span></div></section>
    <section class="panel"><div class="panel-head"><div><span>RULE SIMULATOR</span><h3>Regeln ohne Mailbox testen</h3></div><span class="badge soft">0 SIDE EFFECTS</span></div><div class="form-grid two"><label class="field"><span>Absender</span><input id="rule-sim-sender" value="person@firma.de"></label><label class="field"><span>LLM-Aktion</span><select id="rule-sim-action">${['classify','create_draft','mark_read','move','archive','delete','send_reply','forward'].map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label><label class="field"><span>Confidence</span><input id="rule-sim-confidence" type="number" min="0" max="1" step="0.01" value="0.90"></label><label class="field"><span>Priorität</span><select id="rule-sim-priority">${['normal','low','high','urgent'].map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label><label class="field"><span>Kategorie</span><select id="rule-sim-category">${['other','personal','work','finance','support','sales','newsletter','notification','security'].map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label></div><button class="btn primary" id="rule-simulate">Regel simulieren</button>${renderRuleSimulation()}</section></div>
    <section class="panel full"><div class="panel-head"><div><span>SHADOW REPORTS</span><h3>Was der Agent getan hätte</h3></div><span class="badge soft">LOKAL</span></div>${reports.length?reports.map(shadowReportCard).join(''):emptyState('shield','Noch kein Shadow-Report','Starte einen Historical Replay oder aktiviere Shadow Mode für neue Mails.')}</section>
  </div>`;
}
async function loadShadowStatus(silent=false){
  try{shadowStatus=await get('/v1/agent/shadow');}
  catch(e){if(!silent)showNotice(e.message,'error');}
}
async function setExecutionMode(mode){
  if(!runtimeSettings)return;
  const behavior={...(runtimeSettings.behavior||{}),execution_mode:mode};
  try{runtimeSettings=await put('/v1/settings/behavior',{behavior});await loadShadowStatus(true);showNotice(mode==='shadow'?'Shadow Mode aktiviert. Produktive Mail-Aktionen sind gesperrt.':'Live Mode aktiviert.');render();}
  catch(e){showNotice(e.message,'error');}
}
async function startShadowReplay(){
  const mailbox=dashboard.mailboxes[0];
  const limit=Number(document.getElementById('shadow-replay-limit')?.value||25);
  shadowLoading=true;render();
  try{
    let job=await post('/v1/agent/shadow/replay',{mailbox_id:mailbox?.mailbox_id||null,limit});
    showNotice(`Shadow-Replay mit ${limit} Mails gestartet.`);
    while(['queued','running'].includes(job.status)){
      await new Promise(resolve=>setTimeout(resolve,900));
      job=await get(`/v1/agent/shadow/jobs/${encodeURIComponent(job.job_id)}`);
      await loadShadowStatus(true);render();
    }
    await loadShadowStatus(true);
    if(job.status==='completed')showNotice('Shadow-Replay abgeschlossen · 0 Side Effects.');
    else showNotice(job.error||'Shadow-Replay fehlgeschlagen.','error');
  }catch(e){showNotice(e.message,'error');}
  finally{shadowLoading=false;await loadShadowStatus(true);render();}
}
async function simulateRule(){
  const sender=document.getElementById('rule-sim-sender')?.value?.trim()||'';
  const action=document.getElementById('rule-sim-action')?.value||'classify';
  const confidence=Number(document.getElementById('rule-sim-confidence')?.value||0.9);
  const priority=document.getElementById('rule-sim-priority')?.value||'normal';
  const category=document.getElementById('rule-sim-category')?.value||'other';
  try{ruleSimulation=await post('/v1/agent/rules/simulate',{sender,action,confidence,priority,category,needs_reply:action==='send_reply'});showNotice('Regel simuliert · nichts wurde verändert.');render();}
  catch(e){showNotice(e.message,'error');}
}

function brainLearningCard(item){return `<div class="security-block">'''
    text = replace_once(text, old, shadow_ui, "shadow center UI")
    old = '''  const behavior=rs.behavior||{enabled:true,auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,thread_context_messages:8,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[],rules:[]};
'''
    new = '''  const behavior=rs.behavior||{enabled:true,execution_mode:'live',auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,thread_context_messages:8,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[],rules:[]};
'''
    text = replace_once(text, old, new, "behavior default execution mode")
    old = '''<div class="setting-row"><span>Agent aktiv</span><input id="behavior-enabled" type="checkbox" ${checked(behavior.enabled)}></div><div class="setting-row"><span>Neue Mails automatisch analysieren</span>'''
    new = '''<div class="setting-row"><span>Agent aktiv</span><input id="behavior-enabled" type="checkbox" ${checked(behavior.enabled)}></div><label class="field"><span>Ausführungsmodus</span><select id="behavior-execution-mode"><option value="live" ${behavior.execution_mode!=='shadow'?'selected':''}>Live · Policy-gesteuert</option><option value="shadow" ${behavior.execution_mode==='shadow'?'selected':''}>Shadow · nur simulieren</option></select></label><div class="setting-row"><span>Neue Mails automatisch analysieren</span>'''
    text = replace_once(text, old, new, "settings execution mode")
    old = '''const behavior={...current,enabled:!!document.getElementById('behavior-enabled')?.checked,auto_analyze_new_mail:'''
    new = '''const behavior={...current,enabled:!!document.getElementById('behavior-enabled')?.checked,execution_mode:document.getElementById('behavior-execution-mode')?.value||current.execution_mode||'live',auto_analyze_new_mail:'''
    text = replace_once(text, old, new, "save execution mode")
    old = '''document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(['settings','activity'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true)]);render();});'''
    new = '''document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(['settings','activity','shadow'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true),activeView==='shadow'?loadShadowStatus(true):Promise.resolve()]);render();});'''
    text = replace_once(text, old, new, "shadow view loader")
    old = '''  document.getElementById('activity-refresh')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});
'''
    new = '''  document.getElementById('activity-refresh')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});
  document.getElementById('shadow-enable')?.addEventListener('click',()=>setExecutionMode('shadow'));
  document.getElementById('shadow-disable')?.addEventListener('click',()=>setExecutionMode('live'));
  document.getElementById('shadow-refresh')?.addEventListener('click',async()=>{await loadShadowStatus(false);render();});
  document.getElementById('shadow-replay')?.addEventListener('click',startShadowReplay);
  document.getElementById('rule-simulate')?.addEventListener('click',simulateRule);
'''
    text = replace_once(text, old, new, "shadow button bindings")
    old = '''    showNotice(`Agentenlauf · ${total('processed')} verarbeitet · ${total('drafts')} Entwürfe · ${total('approvals')} Freigaben · ${total('errors')} Fehler · ${pending} warten`);
'''
    new = '''    const shadow=cycles.some(item=>item.execution_mode==='shadow');
    if(shadow)showNotice(`Shadow-Lauf · ${total('processed')} analysiert · ${total('would_draft')} Entwürfe simuliert · ${total('would_approval')} Freigaben simuliert · ${total('errors')} Fehler · 0 Side Effects`);
    else showNotice(`Agentenlauf · ${total('processed')} verarbeitet · ${total('drafts')} Entwürfe · ${total('approvals')} Freigaben · ${total('errors')} Fehler · ${pending} warten`);
'''
    text = replace_once(text, old, new, "shadow run notice")
    path.write_text(text, encoding="utf-8")


def patch_css() -> None:
    path = Path("apps/web/agent-settings.css")
    text = path.read_text(encoding="utf-8").rstrip()
    css = r'''

/* 0.10 Shadow Mode + Rule Simulator */
.shadow-center{display:grid;gap:18px}.shadow-hero{display:flex;justify-content:space-between;align-items:center;min-height:190px;overflow:hidden}.shadow-hero.active{outline:1px solid rgba(96,165,250,.3)}.shadow-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.shadow-progress{height:8px;border-radius:999px;background:rgba(148,163,184,.14);overflow:hidden;margin:14px 0 8px}.shadow-progress span{display:block;height:100%;background:linear-gradient(90deg,#60a5fa,#a78bfa);border-radius:inherit;transition:width .25s ease}.shadow-report{padding:18px 0;border-top:1px solid rgba(148,163,184,.12)}.shadow-report:first-of-type{border-top:0}.shadow-outcomes{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 16px}.shadow-outcomes span{display:flex;gap:7px;align-items:center;padding:7px 10px;border:1px solid rgba(148,163,184,.15);border-radius:999px;font-size:12px;color:#94a3b8}.shadow-outcomes b{color:#e2e8f0}.shadow-result{display:grid;grid-template-columns:1fr auto;gap:5px 14px;padding:13px 0;border-top:1px solid rgba(148,163,184,.1)}.shadow-result p,.shadow-result>small{grid-column:1/-1;margin:0}.shadow-result small{color:#70819d}.rule-sim-result{margin-top:16px;padding-top:12px;border-top:1px solid rgba(148,163,184,.12)}@media(max-width:980px){.shadow-grid{grid-template-columns:1fr}.shadow-hero{align-items:flex-start}}
'''
    if "/* 0.10 Shadow Mode + Rule Simulator */" not in text:
        text += css
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def patch_versions() -> None:
    replacements = {
        "pyproject.toml": ('version = "0.9.0"', 'version = "0.10.0"'),
        "apps/launcher/mail_agent_launcher/main.py": ('APP_VERSION = "0.9.0"', 'APP_VERSION = "0.10.0"'),
        "packages/agent_core/mail_agent_core/identity.py": ('app_version: str = "0.9.0"', 'app_version: str = "0.10.0"'),
        "packaging/windows/MailAgent.iss": ('#define MyAppVersion "0.9.0"', '#define MyAppVersion "0.10.0"'),
    }
    for name, (old, new) in replacements.items():
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        text = replace_once(text, old, new, f"version {name}")
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_mail_store()
    patch_activity()
    patch_main()
    patch_app()
    patch_css()
    patch_versions()
    print("MAIL-AGENT 0.10.0 Shadow Mode integration applied.")
