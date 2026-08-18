from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"Marker missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"Marker not unique in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


main = "apps/gateway/mail_agent_gateway/main.py"
replace_once(
    main,
    "from mail_agent_core.identity import IdentityManager\n",
    "from mail_agent_core.identity import IdentityManager\nfrom mail_agent_core.models import AgentBehaviorSettings\n",
)
replace_once(main, "from .audit import AuditLog\n", "from .agent_runtime import AgentRuntime\nfrom .audit import AuditLog\n")
replace_once(
    main,
    "    AgentAnalyzeRequest,\n",
    "    AgentAnalyzeRequest,\n    AgentRunRequest,\n    BehaviorSettingsRequest,\n    LLMSettingsRequest,\n    ProfileSettingsRequest,\n",
)
replace_once(
    main,
    'providers = {\n    "ollama": OllamaProvider(settings.ollama_base_url),\n    "codex": CodexCliProvider(settings.codex_binary),\n}\n_sync_stop = asyncio.Event()\n',
    'providers = {\n    "ollama": OllamaProvider(settings.ollama_base_url),\n    "codex": CodexCliProvider(settings.codex_binary),\n}\nagent_runtime = AgentRuntime(\n    mail_agent=mail_agent,\n    identity_manager=identity_manager,\n    mail_store=mail_store,\n    state_store=state_store,\n    providers=providers,\n    audit_log=audit_log,\n)\n_sync_stop = asyncio.Event()\n',
)
replace_once(
    main,
    '        audit_log.append("mailbox_synced", details=result)\n        return result\n',
    '''        audit_log.append("mailbox_synced", details=result)
        state = state_store.read()
        if state.get("onboarding_completed") and state.get("configuration"):
            try:
                result["agent"] = await agent_runtime.run_mailbox(mailbox_id)
            except Exception as agent_exc:
                audit_log.append(
                    "agent_cycle_failed",
                    details={"mailbox_id": mailbox_id, "error": str(agent_exc)},
                )
                result["agent"] = {
                    "mailbox_id": mailbox_id,
                    "processed": 0,
                    "error": str(agent_exc),
                }
        return result
''',
)
replace_once(main, 'APP_VERSION = "0.3.0"', 'APP_VERSION = "0.4.0"')
replace_once(
    main,
    '    state["configuration"] = {\n        "profile": body.profile.model_dump(mode="json"),\n        "provider": body.provider,\n        "model": body.model,\n    }\n',
    '    state["configuration"] = {\n        "profile": body.profile.model_dump(mode="json"),\n        "provider": body.provider,\n        "model": body.model,\n        "behavior": AgentBehaviorSettings().model_dump(mode="json"),\n    }\n',
)

settings_routes = '''

def _configuration_or_409() -> tuple[dict, dict]:
    state = state_store.read()
    config = state.get("configuration")
    if not state.get("onboarding_completed") or not isinstance(config, dict):
        raise HTTPException(status_code=409, detail="Onboarding is not complete")
    return state, config


async def _settings_payload() -> dict:
    _state, config = _configuration_or_409()
    identity = asdict(identity_manager.load())
    catalog: dict[str, dict] = {}
    for name, provider in providers.items():
        health_result = await provider.health()
        models: list[str] = []
        if health_result.available:
            try:
                models = await provider.list_models()
            except Exception:
                models = []
        catalog[name] = {
            "available": health_result.available,
            "detail": health_result.detail,
            "models": models,
        }
    behavior = AgentBehaviorSettings.model_validate(config.get("behavior") or {})
    return {
        "identity": identity,
        "provider": config["provider"],
        "model": config["model"],
        "profile": config["profile"],
        "behavior": behavior.model_dump(mode="json"),
        "providers": catalog,
        "invariants": {
            "agent_identity_required": True,
            "agent_signature_required": True,
            "agent_signature_removable": False,
            "send_requires_approval": True,
        },
    }


@app.get("/v1/settings")
async def get_runtime_settings() -> dict:
    return await _settings_payload()


@app.put("/v1/settings/llm")
async def update_llm_settings(body: LLMSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    provider = providers[body.provider]
    health_result = await provider.health()
    if not health_result.available:
        raise HTTPException(status_code=409, detail=health_result.detail)
    config["provider"] = body.provider
    config["model"] = body.model
    state["configuration"] = config
    state_store.write(state)
    audit_log.append(
        "llm_settings_changed",
        details={"provider": body.provider, "model": body.model},
    )
    return await _settings_payload()


@app.put("/v1/settings/behavior")
async def update_behavior_settings(body: BehaviorSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    config["behavior"] = body.behavior.model_dump(mode="json")
    state["configuration"] = config
    state_store.write(state)
    audit_log.append("agent_behavior_changed", details=config["behavior"])
    return await _settings_payload()


@app.put("/v1/settings/profile")
async def update_profile_settings(body: ProfileSettingsRequest) -> dict:
    state, config = _configuration_or_409()
    identity = identity_manager.load()
    if body.profile.owner_id != identity.owner_id:
        raise HTTPException(status_code=409, detail="Profile owner does not match Agent-ID owner")
    profile = body.profile.model_copy(update={"agent_name": identity.agent_name})
    config["profile"] = profile.model_dump(mode="json")
    state["configuration"] = config
    state_store.write(state)
    audit_log.append(
        "agent_profile_changed",
        details={"agent_id": identity.agent_id, "autonomy": profile.autonomy_mode.value},
    )
    return await _settings_payload()


@app.post("/v1/providers/codex/login")
async def start_codex_chatgpt_login() -> dict:
    provider = providers["codex"]
    if not isinstance(provider, CodexCliProvider):
        raise HTTPException(status_code=500, detail="Codex provider is unavailable")
    try:
        detail = provider.start_chatgpt_login()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_log.append("chatgpt_login_started", details={"provider": "codex"})
    return {"started": True, "detail": detail}


@app.post("/v1/agent/run")
async def run_agent_cycle(body: AgentRunRequest) -> dict:
    _configuration_or_409()
    mailbox_ids = (
        [body.mailbox_id]
        if body.mailbox_id
        else [item["mailbox_id"] for item in _configured_mailboxes()]
    )
    if not mailbox_ids:
        raise HTTPException(status_code=409, detail="No mailbox is configured")
    results = []
    for mailbox_id in mailbox_ids:
        try:
            _mailbox_by_id(mailbox_id)
            results.append(await agent_runtime.run_mailbox(mailbox_id, force=body.force))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown mailbox: {mailbox_id}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"results": results}

'''
main_path = Path(main)
main_text = main_path.read_text(encoding="utf-8")
if '@app.get("/v1/settings")' not in main_text:
    marker = '@app.get("/v1/audit")\n'
    if main_text.count(marker) != 1:
        raise SystemExit("Settings insertion marker missing or not unique")
    main_text = main_text.replace(marker, settings_routes + marker, 1)
    main_path.write_text(main_text, encoding="utf-8")

main_text = main_path.read_text(encoding="utf-8")
if "return await agent_runtime.analyze_message(body.message, create_artifacts=True)" not in main_text:
    pattern = re.compile(
        r'@app\.post\("/v1/agent/analyze"\)\nasync def analyze_mail\(body: AgentAnalyzeRequest\) -> dict:\n.*?\n\ndef _oauth_result_page',
        re.S,
    )
    replacement = '''@app.post("/v1/agent/analyze")
async def analyze_mail(body: AgentAnalyzeRequest) -> dict:
    try:
        return await agent_runtime.analyze_message(body.message, create_artifacts=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model analysis failed: {exc}") from exc


def _oauth_result_page'''
    main_text, count = pattern.subn(replacement, main_text, count=1)
    if count != 1:
        raise SystemExit("Analyze route replacement failed")
    main_path.write_text(main_text, encoding="utf-8")

app_path = Path("apps/web/app.js")
app_text = app_path.read_text(encoding="utf-8")
if "let runtimeSettings = null;" not in app_text:
    app_text = app_text.replace(
        "let updateLoading = false;\n",
        "let updateLoading = false;\nlet runtimeSettings = null;\nlet settingsProbe = null;\n",
        1,
    )
if "const put = " not in app_text:
    app_text = app_text.replace(
        "const post = (path, body) => request(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });\n",
        "const post = (path, body) => request(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });\nconst put = (path, body) => request(path, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });\n",
        1,
    )
app_text = app_text.replace("MAIL-AGENT v0.3.0 · Lokales Gateway", "MAIL-AGENT v0.4.0 · Lokales Gateway")

if "chatgpt-login-setup" not in app_text:
    step3 = re.compile(r"  if \(step===3\) \{.*?\n  if \(step===4\)", re.S)
    new_step3 = r'''  if (step===3) {
    const models=probe?.models||[];
    const login=form.provider==='codex'?`<div class="security-note">${icon('spark',18)}<span><b>ChatGPT ohne API-Key</b><small>Der offizielle Codex-Client öffnet den Browser. Du meldest dich direkt bei OpenAI an; MAIL-AGENT erhält kein ChatGPT-Passwort.</small></span></div><div class="inline-actions left"><button class="btn secondary" id="chatgpt-login-setup">Mit ChatGPT anmelden</button></div>`:'';
    body=`<div class="card-heading"><span class="card-icon">${icon('spark',22)}</span><div><h2>Welches Modell soll denken?</h2><p>Du kannst lokal mit Ollama oder über deinen ChatGPT-Login im offiziellen Codex-Client arbeiten.</p></div></div><div class="selection-grid two">${choice('provider','ollama','Ollama','Komplett lokal. Ideal für maximale Privatsphäre.',form.provider==='ollama','home')}${choice('provider','codex','ChatGPT / OpenAI','Browser-Login über den offiziellen Codex-Client. Kein API-Key zum Kopieren.',form.provider==='codex','spark')}</div>${login}<div class="inline-actions left"><button class="btn secondary" id="provider-test" ${busy?'disabled':''}>Provider prüfen</button>${probe?`<span class="probe ${probe.available?'ok':'bad'}">${probe.available?'Bereit':'Nicht verfügbar'}</span>`:''}</div>${models.length?selectField('Modell','model-select',models.map(m=>[m,m]),form.model):''}${actions(2,'Weiter','next',!probe?.available)}`;
  }
  if (step===4)'''
    app_text, count = step3.subn(new_step3, app_text, count=1)
    if count != 1:
        raise SystemExit("Setup LLM step replacement failed")
if "document.getElementById('chatgpt-login-setup')" not in app_text:
    app_text = app_text.replace(
        "  document.getElementById('provider-test')?.addEventListener('click',probeProvider);\n",
        "  document.getElementById('provider-test')?.addEventListener('click',probeProvider);\n  document.getElementById('chatgpt-login-setup')?.addEventListener('click',startChatGptLogin);\n",
        1,
    )

if "content=renderAgentSettings();" not in app_text:
    settings_pattern = re.compile(
        r"  if\(activeView==='settings'\) content=`.*?`;\n  app\.innerHTML=dashboardLayout\(content\);",
        re.S,
    )
    app_text, count = settings_pattern.subn(
        "  if(activeView==='settings') content=renderAgentSettings();\n  app.innerHTML=dashboardLayout(content);",
        app_text,
        count=1,
    )
    if count != 1:
        raise SystemExit("Settings view replacement failed")

settings_js = r'''
function checked(value){return value?'checked':'';}
function renderAgentSettings(){
  const rs=runtimeSettings||{};
  const id=rs.identity||identity||{};
  const profile=rs.profile||{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType,autonomy_mode:form.autonomy,language:form.language,tone:form.tone,email_signature:form.emailSignature};
  const behavior=rs.behavior||{enabled:true,auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[]};
  const provider=rs.provider||form.provider||'ollama';
  const catalog=rs.providers||{};
  const models=catalog[provider]?.models||[];
  const model=rs.model||form.model||'default';
  const modelControl=provider==='ollama'&&models.length
    ? `<label class="field"><span>Modell</span><select id="settings-model">${models.map(m=>`<option value="${esc(m)}" ${m===model?'selected':''}>${esc(m)}</option>`).join('')}</select></label>`
    : `<label class="field"><span>Modell</span><input id="settings-model" value="${esc(model)}" placeholder="default oder Modell-ID"></label>`;
  const days=[['Mo',0],['Di',1],['Mi',2],['Do',3],['Fr',4],['Sa',5],['So',6]].map(([label,day])=>`<label class="day-chip"><input type="checkbox" data-agent-day="${day}" ${checked((behavior.active_days||[]).includes(day))}><span>${label}</span></label>`).join('');
  const providerDetail=settingsProbe?.provider===provider?settingsProbe.detail:(catalog[provider]?.detail||'Noch nicht geprüft');
  return `<div class="settings-grid agent-settings-grid">
    <section class="panel"><div class="panel-head"><div><span>AGENTEN-IDENTITÄT</span><h3>${esc(id.agent_name||form.agentName||'MAIL-AGENT')}</h3></div><span class="badge soft">UNVERÄNDERLICH</span></div><div class="setting-row"><span>Agent-ID</span><b class="mono">${esc(id.agent_id||'—')}</b></div><div class="setting-row"><span>Fingerprint</span><b class="mono small-mono">${esc(id.fingerprint||'—')}</b></div><div class="security-block">${icon('shield',22)}<div><b>Identifikation ist zwingend</b><p>Jeder vom Agenten erzeugte Entwurf, jede Antwort und jede Weiterleitung erhält automatisch Agent-ID und Fingerprint. Diese Pflicht kann weder vom Modell noch in den Einstellungen abgeschaltet werden.</p></div></div></section>
    <section class="panel"><div class="panel-head"><div><span>LLM</span><h3>Modell jederzeit wechseln</h3></div><span class="badge soft">${esc(provider)}</span></div><div class="form-grid two"><label class="field"><span>Provider</span><select id="settings-provider"><option value="ollama" ${provider==='ollama'?'selected':''}>Ollama · lokal</option><option value="codex" ${provider==='codex'?'selected':''}>ChatGPT / OpenAI · Browser-Login</option></select></label>${modelControl}</div><div class="security-block">${icon('spark',22)}<div><b>${catalog[provider]?.available?'Provider bereit':'Provider prüfen'}</b><p>${esc(providerDetail)}</p></div></div><div class="inline-actions left"><button class="btn secondary" id="settings-provider-test">Provider prüfen</button>${provider==='codex'?'<button class="btn secondary" id="settings-chatgpt-login">Mit ChatGPT anmelden</button>':''}<button class="btn primary" id="settings-save-llm">LLM speichern</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>PERSÖNLICHKEIT</span><h3>Antwortstil & Kontrolle</h3></div></div><div class="form-grid two"><label class="field"><span>Autonomie</span><select id="settings-autonomy"><option value="observer" ${profile.autonomy_mode==='observer'?'selected':''}>Observer</option><option value="assistant" ${profile.autonomy_mode==='assistant'?'selected':''}>Assistant</option><option value="copilot" ${profile.autonomy_mode==='copilot'?'selected':''}>Copilot</option><option value="autonomous" ${profile.autonomy_mode==='autonomous'?'selected':''}>Autonomous</option></select></label><label class="field"><span>Ton</span><select id="settings-tone"><option value="friendly" ${profile.tone==='friendly'?'selected':''}>Freundlich</option><option value="professional" ${profile.tone==='professional'?'selected':''}>Professionell</option><option value="direct" ${profile.tone==='direct'?'selected':''}>Direkt</option><option value="warm" ${profile.tone==='warm'?'selected':''}>Warm</option></select></label><label class="field"><span>Sprache</span><select id="settings-language"><option value="de" ${profile.language==='de'?'selected':''}>Deutsch</option><option value="en" ${profile.language==='en'?'selected':''}>English</option></select></label></div><label class="field"><span>Persönliche Signatur vor der Agent-ID</span><textarea id="settings-email-signature" rows="4">${esc(profile.email_signature||'')}</textarea></label><div class="security-note">${icon('lock',18)}<span>Die persönliche Signatur ist frei änderbar. Die darunter liegende MAIL-AGENT-ID-Signatur ist technisch verpflichtend.</span></div><div class="inline-actions left"><button class="btn primary" id="settings-save-profile">Profil speichern</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>AGENTISCHES VERHALTEN</span><h3>Wann und wie der Agent arbeitet</h3></div><span class="badge ${behavior.enabled?'':'soft'}">${behavior.enabled?'AKTIV':'PAUSIERT'}</span></div><div class="setting-row"><span>Agent aktiv</span><input id="behavior-enabled" type="checkbox" ${checked(behavior.enabled)}></div><div class="setting-row"><span>Neue Mails automatisch analysieren</span><input id="behavior-auto-analyze" type="checkbox" ${checked(behavior.auto_analyze_new_mail)}></div><div class="setting-row"><span>Antwortentwürfe automatisch vorbereiten</span><input id="behavior-auto-drafts" type="checkbox" ${checked(behavior.auto_create_drafts)}></div><div class="form-grid two"><label class="field"><span>Mindest-Konfidenz</span><input id="behavior-confidence" type="number" min="0" max="1" step="0.01" value="${esc(behavior.minimum_confidence)}"></label><label class="field"><span>Max. Mails pro Zyklus</span><input id="behavior-max-messages" type="number" min="1" max="200" value="${esc(behavior.max_messages_per_cycle)}"></label><label class="field"><span>Aktiv ab</span><input id="behavior-from" type="time" value="${esc(behavior.active_from)}"></label><label class="field"><span>Aktiv bis</span><input id="behavior-until" type="time" value="${esc(behavior.active_until)}"></label></div><div class="field"><span>Aktive Tage</span><div class="day-selector">${days}</div></div><label class="field"><span>Nie automatisch bearbeiten · Absender/Domain, eine Zeile pro Regel</span><textarea id="behavior-blocked-senders" rows="4" placeholder="newsletter@example.com\n@example.org">${esc((behavior.never_auto_act_senders||[]).join('\n'))}</textarea></label><div class="security-block">${icon('shield',22)}<div><b>Versand bleibt menschlich freigabepflichtig</b><p>Agentisch bedeutet: automatisch erkennen, analysieren und signierte Entwürfe vorbereiten. Senden, Weiterleiten und Löschen bleiben als High-Risk-Aktionen freigabepflichtig.</p></div></div><div class="inline-actions left"><button class="btn primary" id="settings-save-behavior">Verhalten speichern</button><button class="btn secondary" id="settings-run-agent">Agent jetzt ausführen</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>SICHERHEIT</span><h3>Unverhandelbare Grenzen</h3></div></div><div class="security-block">${icon('lock',22)}<div><b>Credential Vault aktiv</b><p>Mailbox-Secrets, OAuth-Tokens und Agent-Schlüssel bleiben lokal geschützt.</p></div></div><div class="security-block">${icon('shield',22)}<div><b>Policy Engine vor Ausführung</b><p>Das LLM schlägt Aktionen nur vor. Regeln, Freigaben und Agent-ID-Pflicht werden deterministisch im Gateway erzwungen.</p></div></div></section>
  </div>`;
}
async function loadRuntimeSettings(silent=false){
  try{
    runtimeSettings=await get('/v1/settings');
    identity=runtimeSettings.identity||identity;
    const p=runtimeSettings.profile||{};
    form.provider=runtimeSettings.provider||form.provider;
    form.model=runtimeSettings.model||form.model;
    form.autonomy=p.autonomy_mode||form.autonomy;
    form.language=p.language||form.language;
    form.tone=p.tone||form.tone;
    form.emailSignature=p.email_signature||form.emailSignature;
  }catch(e){if(!silent)showNotice(e.message,'error');}
}
async function probeSettingsProvider(){
  const provider=document.getElementById('settings-provider')?.value||runtimeSettings?.provider||form.provider;
  try{settingsProbe=await post('/v1/providers/probe',{provider});showNotice(settingsProbe.available?'Provider ist bereit.':settingsProbe.detail,settingsProbe.available?'success':'error');}
  catch(e){showNotice(e.message,'error');}
  render();
}
async function saveLlmSettings(){
  const provider=document.getElementById('settings-provider')?.value||form.provider;
  const model=document.getElementById('settings-model')?.value?.trim()||'default';
  try{runtimeSettings=await put('/v1/settings/llm',{provider,model});form.provider=provider;form.model=model;settingsProbe=null;showNotice('LLM-Einstellung gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
async function startChatGptLogin(){
  try{const result=await post('/v1/providers/codex/login',{});showNotice(result.detail||'ChatGPT-Anmeldung wurde gestartet.');}
  catch(e){showNotice(e.message,'error');}
}
async function saveProfileSettings(){
  const current=runtimeSettings?.profile||{};
  const profile={...current,owner_id:current.owner_id||form.ownerId,agent_name:current.agent_name||form.agentName,usage_type:current.usage_type||form.usageType,autonomy_mode:document.getElementById('settings-autonomy')?.value||form.autonomy,language:document.getElementById('settings-language')?.value||form.language,tone:document.getElementById('settings-tone')?.value||form.tone,email_signature:document.getElementById('settings-email-signature')?.value||''};
  try{runtimeSettings=await put('/v1/settings/profile',{profile});await loadRuntimeSettings(true);showNotice('Agentenprofil gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
async function saveBehaviorSettings(){
  const days=[...document.querySelectorAll('[data-agent-day]:checked')].map(el=>Number(el.dataset.agentDay));
  const blocked=(document.getElementById('behavior-blocked-senders')?.value||'').split(/[\n,]+/).map(v=>v.trim()).filter(Boolean);
  const current=runtimeSettings?.behavior||{};
  const behavior={...current,enabled:!!document.getElementById('behavior-enabled')?.checked,auto_analyze_new_mail:!!document.getElementById('behavior-auto-analyze')?.checked,auto_create_drafts:!!document.getElementById('behavior-auto-drafts')?.checked,minimum_confidence:Number(document.getElementById('behavior-confidence')?.value||0.72),max_messages_per_cycle:Number(document.getElementById('behavior-max-messages')?.value||20),active_from:document.getElementById('behavior-from')?.value||'00:00',active_until:document.getElementById('behavior-until')?.value||'23:59',active_days:days,never_auto_act_senders:blocked};
  try{runtimeSettings=await put('/v1/settings/behavior',{behavior});showNotice('Agentisches Verhalten gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
async function runAgentNow(){
  const mailbox=dashboard.mailboxes[0];
  try{const result=await post('/v1/agent/run',{mailbox_id:mailbox?.mailbox_id||null,force:true});await loadDashboard(true);const cycle=result.results?.[0]||{};showNotice(`Agentenlauf abgeschlossen · ${cycle.processed||0} verarbeitet, ${cycle.drafts||0} Entwürfe.`);render();}
  catch(e){showNotice(e.message,'error');}
}
'''
if "function renderAgentSettings(){" not in app_text:
    marker = "function renderUpdatePanel(){\n"
    if app_text.count(marker) != 1:
        raise SystemExit("Update panel marker missing or not unique")
    app_text = app_text.replace(marker, settings_js + "\n" + marker, 1)

old_bind = "function bindDashboard(){document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>{activeView=el.dataset.view;render();});document.getElementById('sync-now')?.addEventListener('click',syncNow);document.querySelectorAll('[data-approve]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.approve,'approve'));document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));}"
new_bind = r'''function bindDashboard(){
  document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(activeView==='settings'&&!runtimeSettings)await loadRuntimeSettings(true);render();});
  document.getElementById('sync-now')?.addEventListener('click',syncNow);
  document.querySelectorAll('[data-approve]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.approve,'approve'));
  document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));
  document.getElementById('settings-provider-test')?.addEventListener('click',probeSettingsProvider);
  document.getElementById('settings-chatgpt-login')?.addEventListener('click',startChatGptLogin);
  document.getElementById('settings-save-llm')?.addEventListener('click',saveLlmSettings);
  document.getElementById('settings-save-profile')?.addEventListener('click',saveProfileSettings);
  document.getElementById('settings-save-behavior')?.addEventListener('click',saveBehaviorSettings);
  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);
  document.getElementById('settings-provider')?.addEventListener('change',event=>{if(!runtimeSettings)return;runtimeSettings.provider=event.target.value;runtimeSettings.model=event.target.value==='codex'?'default':(runtimeSettings.providers?.[event.target.value]?.models?.[0]||'');settingsProbe=null;render();});
}'''
if old_bind in app_text:
    app_text = app_text.replace(old_bind, new_bind, 1)
elif "settings-save-behavior" not in app_text[app_text.find("function bindDashboard(){"):app_text.find("async function loadDashboard")]:
    raise SystemExit("Dashboard bind replacement failed")

app_text = app_text.replace(
    "installed=true;await loadDashboard(true);showNotice('MAIL-AGENT ist bereit.')",
    "installed=true;await Promise.all([loadDashboard(true),loadRuntimeSettings(true)]);showNotice('MAIL-AGENT ist bereit.')",
    1,
)
app_text = app_text.replace(
    "if(installed)await loadDashboard(true);",
    "if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true)]);",
    1,
)
app_path.write_text(app_text, encoding="utf-8")

replace_once("apps/launcher/mail_agent_launcher/main.py", 'APP_VERSION = "0.3.0"', 'APP_VERSION = "0.4.0"')
replace_once("packaging/windows/MailAgent.iss", '#define MyAppVersion "0.3.0"', '#define MyAppVersion "0.4.0"')
replace_once("pyproject.toml", 'version = "0.3.0"', 'version = "0.4.0"')
