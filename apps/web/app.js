const apiBase = location.origin;
const onboardingSteps = ['Identität', 'Einsatz', 'Postfach', 'KI', 'Persönlichkeit', 'Sicherheit'];
let step = 0;
let identity = null;
let probe = null;
let busy = false;
let installed = false;
let activeView = 'overview';
let dashboard = { mailboxes: [], approvals: [], messages: [], drafts: [] };
let mailboxConnected = false;
let mailboxId = null;
let updateStatus = null;
let updateLoading = false;
let runtimeSettings = null;
let brainStatus = null;
let brainLoading = false;
let shadowStatus = null;
let shadowLoading = false;
let ruleSimulation = null;
let systemHealth = null;
let systemHealthLoading = false;
let settingsProbe = null;
let editingDraftId = null;
let mailboxConnector = null;
let oauthProviders = { google: { configured: false }, microsoft: { configured: false } };
const form = {
  ownerId: '', agentName: 'Nova', usageType: 'private', provider: 'ollama', model: '',
  autonomy: 'assistant', tone: 'friendly', language: 'de', emailSignature: '',
  emailAddress: '', mailboxUsername: '', mailboxPassword: '', imapHost: '', imapPort: 993,
  smtpHost: '', smtpPort: 465,
};

const app = document.querySelector('#app');
const notice = document.querySelector('#notice');

function esc(value = '') {
  return String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}
function icon(name, size = 20) {
  const paths = {
    mail:'<path d="M4 6h16v12H4z"/><path d="m4 7 8 6 8-6"/>',
    home:'<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/>',
    shield:'<path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
    draft:'<path d="M5 4h10l4 4v12H5z"/><path d="M15 4v5h4"/><path d="M8 13h8M8 16h6"/>',
    inbox:'<path d="M4 5h16v14H4z"/><path d="M4 14h5l2 2h2l2-2h5"/>',
    sync:'<path d="M20 7h-5V2"/><path d="M20 7a8 8 0 0 0-14-2M4 17h5v5"/><path d="M4 17a8 8 0 0 0 14 2"/>',
    settings:'<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 15 6l-.3-2.6h-4L10.5 6A7 7 0 0 0 9 7.1l-2.4-1-2 3.4L6.6 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A7 7 0 0 0 10.5 18l.3 2.6h4L15 18a7 7 0 0 0 1.5-1.1l2.4 1 2-3.4-2-1.5c.1-.3.1-.7.1-1z"/>',
    spark:'<path d="m12 3 1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="m19 14 .7 2.3L22 17l-2.3.7L19 20l-.7-2.3L16 17l2.3-.7z"/>',
    chevron:'<path d="m9 18 6-6-6-6"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    x:'<path d="m6 6 12 12M18 6 6 18"/>',
    user:'<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-5 4-7 8-7s6.5 2 8 7"/>',
    lock:'<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  };
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
}
function showNotice(text, kind='success') {
  notice.textContent = text;
  notice.className = `toast ${kind}`;
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => notice.className = 'toast hidden', 3800);
}
async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
const get = path => request(path);
const post = (path, body) => request(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
const put = (path, body) => request(path, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });

function brand(compact=false) {
  return `<div class="brand ${compact?'compact':''}"><div class="brand-logo">${icon('mail',22)}</div><div><strong>MAIL<span>·</span>AGENT</strong>${compact?'':'<small>Private email intelligence</small>'}</div></div>`;
}
function stepper() {
  return `<div class="setup-stepper">${onboardingSteps.map((label, i) => `<div class="setup-dot ${i < step ? 'done' : ''} ${i === step ? 'active' : ''}"><span>${i < step ? icon('check',13) : i+1}</span><small>${label}</small></div>`).join('')}</div>`;
}
function setupLayout(content) {
  return `<main class="setup-page"><section class="setup-aside">${brand()}<div class="setup-aside-copy"><span class="kicker">SETUP IN WENIGEN MINUTEN</span><h1>Dein Postfach.<br><em>Dein Agent.</em></h1><p>MAIL-AGENT bereitet Antworten, Entscheidungen, Termine und dein Tagesbriefing lokal vor.</p></div><div class="trust-pill">${icon('shield',18)}<span><b>Local-first</b><small>Schlüssel und Mail-Zugang bleiben bei dir.</small></span></div></section><section class="setup-main"><div class="setup-top"><span>Schritt ${step+1} von ${onboardingSteps.length}</span><b>${onboardingSteps[step]}</b></div>${stepper()}<div class="setup-card">${content}</div><div class="setup-foot">MAIL-AGENT v0.17.3 · Lokales Gateway</div></section></main>`;
}
function field(label, id, value='', type='text', placeholder='') {
  return `<label class="field"><span>${label}</span><input id="${id}" type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}"></label>`;
}
function selectField(label,id,options,value) {
  return `<label class="field"><span>${label}</span><select id="${id}">${options.map(([v,l])=>`<option value="${v}" ${v===value?'selected':''}>${l}</option>`).join('')}</select></label>`;
}
function choice(group,value,title,text,selected,ico) {
  return `<button class="select-card ${selected?'selected':''}" data-choice-group="${group}" data-choice="${value}"><span class="select-icon">${icon(ico||'spark',20)}</span><span class="select-copy"><b>${title}</b><small>${text}</small></span><span class="select-check">${selected?icon('check',16):''}</span></button>`;
}
function actions(back, nextLabel='Weiter', nextId='next', disabled=false) {
  return `<div class="setup-actions">${back === null ? '<span></span>' : `<button class="btn text" data-back="${back}">Zurück</button>`}<button class="btn primary" id="${nextId}" ${disabled?'disabled':''}>${nextLabel}${icon('chevron',17)}</button></div>`;
}
function saveVisible() {
  const map = [['owner','ownerId'],['agent-name','agentName'],['email-address','emailAddress'],['mailbox-username','mailboxUsername'],['mailbox-password','mailboxPassword'],['imap-host','imapHost'],['smtp-host','smtpHost'],['email-signature','emailSignature']];
  map.forEach(([id,key]) => { const el=document.getElementById(id); if(el) form[key]=el.value; });
  const nmap=[['imap-port','imapPort'],['smtp-port','smtpPort']]; nmap.forEach(([id,key])=>{const el=document.getElementById(id); if(el) form[key]=Number(el.value)||form[key];});
  [['language','language'],['tone','tone'],['model-select','model']].forEach(([id,key])=>{const el=document.getElementById(id); if(el) form[key]=el.value;});
}
function go(next) { saveVisible(); step=Math.max(0,Math.min(onboardingSteps.length-1,next)); render(); }

function renderSetup() {
  let body='';
  if (step===0) body = `<div class="card-heading"><span class="card-icon">${icon('user',22)}</span><div><h2>Wer bekommt diesen Agenten?</h2><p>Wir erzeugen eine eindeutige, kryptografisch signierte Identität für diese Installation.</p></div></div><div class="form-grid one">${field('Owner / Accountname','owner',form.ownerId,'text','z. B. steffen')}${field('Name des Agenten','agent-name',form.agentName,'text','Nova')}</div><div class="security-note">${icon('lock',18)}<span>Der private Ed25519-Schlüssel verlässt dieses Gerät niemals.</span></div>${actions(null,'Weiter','next',!form.ownerId||!form.agentName)}`;
  if (step===1) body = `<div class="card-heading"><span class="card-icon">${icon('spark',22)}</span><div><h2>Wofür soll er arbeiten?</h2><p>Damit setzen wir passende Sicherheits- und Stil-Defaults.</p></div></div><div class="selection-grid">${choice('usage','private','Privat','Alltag, Freunde, Familie und persönliche Kommunikation.',form.usageType==='private','home')}${choice('usage','work','Arbeit','Konservativere Regeln und professioneller Standard.',form.usageType==='work','draft')}${choice('usage','business','Business','Strenge Freigaben für geschäftliche Kommunikation.',form.usageType==='business','shield')}${choice('usage','custom','Individuell','Eigene Regeln und Verhalten frei konfigurieren.',form.usageType==='custom','settings')}</div>${identity?`<div class="success-line">${icon('check',16)} Identität registriert · ${esc(identity.fingerprint.slice(0,12))}…</div>`:''}${actions(0,'Identität anlegen','identity-create',busy)}`;
  if (step===2) {
    const google=oauthProviders.google||{configured:false};
    const microsoft=oauthProviders.microsoft||{configured:false};
    const gmailConnected=mailboxConnected&&mailboxConnector==='gmail_api';
    const microsoftConnected=mailboxConnected&&mailboxConnector==='microsoft_graph';
    const oauthConnected=gmailConnected||microsoftConnected;
    body = `<div class="card-heading"><span class="card-icon">${icon('inbox',22)}</span><div><h2>Postfach verbinden</h2><p>Gmail und Microsoft 365 werden direkt per OAuth verbunden. Kein App-Passwort und keine Serverdaten nötig.</p></div></div><div class="oauth-grid"><button class="oauth-card ${google.configured?'':'unavailable'}" id="google-connect" data-configured="${google.configured?'1':'0'}" ${busy?'disabled':''}><span class="google-mark">G</span><span><b>${gmailConnected?'Gmail verbunden':'Mit Google anmelden'}</b><small>${gmailConnected?esc(form.emailAddress):google.configured?'Google OAuth 2.0 + PKCE':'Google OAuth ist in diesem Build nicht konfiguriert'}</small></span><span class="oauth-arrow">${gmailConnected?icon('check',17):icon('chevron',17)}</span></button><button class="oauth-card ${microsoft.configured?'':'unavailable'}" id="microsoft-connect" data-configured="${microsoft.configured?'1':'0'}" ${busy?'disabled':''}><span class="ms-mark">M</span><span><b>${microsoftConnected?'Microsoft 365 verbunden':'Mit Microsoft anmelden'}</b><small>${microsoftConnected?esc(form.emailAddress):microsoft.configured?'Microsoft OAuth 2.0 + PKCE · Graph':'Microsoft OAuth ist in diesem Build nicht konfiguriert'}</small></span><span class="oauth-arrow">${microsoftConnected?icon('check',17):icon('chevron',17)}</span></button></div>${oauthConnected?`<div class="success-line">${icon('check',16)} ${esc(form.emailAddress)} ist sicher über ${gmailConnected?'Gmail API':'Microsoft Graph'} verbunden.</div>`:''}<div class="separator"><span>oder manuell per IMAP / SMTP</span></div><div class="form-grid two">${field('E-Mail-Adresse','email-address',form.emailAddress,'email','name@example.com')}${field('Benutzername','mailbox-username',form.mailboxUsername,'text','meist E-Mail-Adresse')}${field('IMAP-Server','imap-host',form.imapHost,'text','imap.example.com')}${field('IMAP-Port','imap-port',form.imapPort,'number')}${field('SMTP-Server','smtp-host',form.smtpHost,'text','smtp.example.com')}${field('SMTP-Port','smtp-port',form.smtpPort,'number')}</div>${field('Passwort / App-Passwort','mailbox-password',form.mailboxPassword,'password','••••••••••••')}<div class="security-note">${icon('lock',18)}<span>OAuth-Tokens und manuelle Mail-Secrets werden ausschließlich verschlüsselt im lokalen Vault gespeichert.</span></div><div class="setup-actions"><button class="btn text" data-back="1">Zurück</button><div class="inline-actions"><button class="btn secondary" id="mailbox-test" ${busy?'disabled':''}>IMAP testen</button><button class="btn primary" id="next" ${!mailboxConnected?'disabled':''}>Weiter${icon('chevron',17)}</button></div></div>`;
  }
  if (step===3) {
    const models=probe?.models||[];
    const login=form.provider==='codex'?`<div class="security-note">${icon('spark',18)}<span><b>ChatGPT ohne API-Key</b><small>Der offizielle Codex-Client öffnet den Browser. Du meldest dich direkt bei OpenAI an; MAIL-AGENT erhält kein ChatGPT-Passwort.</small></span></div><div class="inline-actions left"><button class="btn secondary" id="chatgpt-login-setup">Mit ChatGPT anmelden</button></div>`:'';
    body=`<div class="card-heading"><span class="card-icon">${icon('spark',22)}</span><div><h2>Welches Modell soll denken?</h2><p>Du kannst lokal mit Ollama oder über deinen ChatGPT-Login im offiziellen Codex-Client arbeiten.</p></div></div><div class="selection-grid two">${choice('provider','ollama','Ollama','Komplett lokal. Ideal für maximale Privatsphäre.',form.provider==='ollama','home')}${choice('provider','codex','ChatGPT / OpenAI','Browser-Login über den offiziellen Codex-Client. Kein API-Key zum Kopieren.',form.provider==='codex','spark')}</div>${login}<div class="inline-actions left"><button class="btn secondary" id="provider-test" ${busy?'disabled':''}>Provider prüfen</button>${probe?`<span class="probe ${probe.available?'ok':'bad'}">${probe.available?'Bereit':'Nicht verfügbar'}</span>`:''}</div>${models.length?selectField('Modell','model-select',models.map(m=>[m,m]),form.model):''}${actions(2,'Weiter','next',!probe?.available)}`;
  }
  if (step===4) body = `<div class="card-heading"><span class="card-icon">${icon('user',22)}</span><div><h2>Wie soll dein Agent klingen?</h2><p>Diese Persönlichkeit prägt jeden Entwurf, ohne Sicherheitsregeln zu verändern.</p></div></div><div class="form-grid two">${selectField('Sprache','language',[['de','Deutsch'],['en','English']],form.language)}${selectField('Ton','tone',[['friendly','Freundlich'],['professional','Professionell'],['direct','Direkt'],['warm','Warm']],form.tone)}</div><label class="field"><span>E-Mail-Signatur</span><textarea id="email-signature" rows="5" placeholder="Viele Grüße\nSteffen">${esc(form.emailSignature)}</textarea></label>${actions(3)}`;
  if (step===5) body = `<div class="card-heading"><span class="card-icon">${icon('shield',22)}</span><div><h2>Wie selbstständig darf er sein?</h2><p>Du behältst die Kontrolle. Kritische Aktionen bleiben auch im autonomen Modus freigabepflichtig.</p></div></div><div class="selection-list">${choice('autonomy','observer','Observer','Liest und analysiert nur.',form.autonomy==='observer','inbox')}${choice('autonomy','assistant','Assistant','Erstellt zusätzlich sichere Entwürfe.',form.autonomy==='assistant','draft')}${choice('autonomy','copilot','Copilot','Sortiert und archiviert nach Regeln.',form.autonomy==='copilot','sync')}${choice('autonomy','autonomous','Autonomous','Führt erlaubte Low-Risk-Aktionen selbst aus.',form.autonomy==='autonomous','spark')}</div><div class="final-summary"><div><span>Agent</span><b>${esc(form.agentName)}</b></div><div><span>Postfach</span><b>${esc(form.emailAddress)}</b></div><div><span>Modell</span><b>${esc(form.provider)} · ${esc(form.model||'default')}</b></div><div><span>Versand</span><b>Freigabe erforderlich</b></div></div>${actions(4,'MAIL-AGENT aktivieren','finish',busy)}`;
  app.innerHTML=setupLayout(body); bindSetup();
}
function bindSetup() {
  document.querySelectorAll('[data-back]').forEach(el=>el.onclick=()=>go(Number(el.dataset.back)));
  document.querySelectorAll('[data-choice-group]').forEach(el=>el.onclick=()=>{const g=el.dataset.choiceGroup,v=el.dataset.choice;if(g==='usage')form.usageType=v;if(g==='provider'){form.provider=v;form.model=v==='codex'?'default':'';probe=null;}if(g==='autonomy')form.autonomy=v;render();});
  document.getElementById('next')?.addEventListener('click',()=>go(step+1));
  ['owner','agent-name'].forEach(id=>document.getElementById(id)?.addEventListener('input',()=>{saveVisible();render();}));
  document.getElementById('identity-create')?.addEventListener('click',createIdentity);
  document.getElementById('google-connect')?.addEventListener('click',connectGoogle);
  document.getElementById('microsoft-connect')?.addEventListener('click',connectMicrosoft);
  document.getElementById('mailbox-test')?.addEventListener('click',probeMailbox);
  document.getElementById('provider-test')?.addEventListener('click',probeProvider);
  document.getElementById('chatgpt-login-setup')?.addEventListener('click',startChatGptLogin);
  document.getElementById('finish')?.addEventListener('click',finishOnboarding);
}
async function createIdentity(){saveVisible();busy=true;render();try{identity=await post('/v1/onboarding/identity',{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType});step=2;}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function probeMailbox(){saveVisible();busy=true;render();try{const r=await post('/v1/mailboxes/probe',{email_address:form.emailAddress,username:form.mailboxUsername,password:form.mailboxPassword,imap_host:form.imapHost,imap_port:form.imapPort,smtp_host:form.smtpHost,smtp_port:form.smtpPort});mailboxConnected=true;mailboxId=r.mailbox_id;mailboxConnector='imap';form.mailboxPassword='';showNotice('Postfach sicher verbunden.')}catch(e){mailboxConnected=false;showNotice(e.message,'error')}finally{busy=false;render()}}

async function connectGoogle(){
  saveVisible();
  const configured=document.getElementById('google-connect')?.dataset.configured==='1'||!!oauthProviders.google?.configured;
  if(!configured){showNotice('Google OAuth ist für diesen Build noch nicht freigeschaltet. Der Projekt-Client muss einmalig konfiguriert werden.','error');return;}
  const popup=window.open('about:blank','mail-agent-google','popup=yes,width=560,height=760');
  if(!popup){showNotice('Der Browser hat das Google-Anmeldefenster blockiert. Pop-ups für MAIL-AGENT erlauben.','error');return;}
  busy=true;render();
  try{
    const start=await post('/v1/oauth/google/start',{login_hint:form.emailAddress||null});
    popup.location.replace(start.authorization_url);
    const result=await waitForOAuth(start.state,popup,'Google');
    mailboxConnected=true;
    mailboxId=result.mailbox_id;
    mailboxConnector='gmail_api';
    form.emailAddress=result.email_address||form.emailAddress;
    form.mailboxUsername=form.emailAddress;
    showNotice(`Gmail verbunden: ${form.emailAddress}`);
  }catch(e){
    try{if(!popup.closed)popup.close();}catch(_){}
    showNotice(e.message,'error');
  }finally{busy=false;render();}
}

async function connectMicrosoft(){
  saveVisible();
  const configured=document.getElementById('microsoft-connect')?.dataset.configured==='1'||!!oauthProviders.microsoft?.configured;
  if(!configured){showNotice('Microsoft OAuth ist für diesen Build noch nicht freigeschaltet. Der Projekt-Client muss einmalig konfiguriert werden.','error');return;}
  const popup=window.open('about:blank','mail-agent-microsoft','popup=yes,width=560,height=760');
  if(!popup){showNotice('Der Browser hat das Microsoft-Anmeldefenster blockiert. Pop-ups für MAIL-AGENT erlauben.','error');return;}
  busy=true;render();
  try{
    const start=await post('/v1/oauth/microsoft/start',{login_hint:form.emailAddress||null});
    popup.location.replace(start.authorization_url);
    const result=await waitForOAuth(start.state,popup,'Microsoft');
    mailboxConnected=true;
    mailboxId=result.mailbox_id;
    mailboxConnector='microsoft_graph';
    form.emailAddress=result.email_address||form.emailAddress;
    form.mailboxUsername=form.emailAddress;
    showNotice(`Microsoft 365 verbunden: ${form.emailAddress}`);
  }catch(e){
    try{if(!popup.closed)popup.close();}catch(_){}
    showNotice(e.message,'error');
  }finally{busy=false;render();}
}

async function waitForOAuth(state,popup,providerLabel='OAuth'){
  const deadline=Date.now()+5*60*1000;
  while(Date.now()<deadline){
    const session=await get(`/v1/oauth/sessions/${encodeURIComponent(state)}`);
    if(session.status==='complete'){try{if(!popup.closed)popup.close();}catch(_){}return session;}
    if(session.status==='error')throw new Error(session.error||`${providerLabel}-Anmeldung fehlgeschlagen.`);
    await new Promise(resolve=>setTimeout(resolve,700));
  }
  throw new Error(`${providerLabel}-Anmeldung hat zu lange gedauert. Bitte erneut versuchen.`);
}

async function probeProvider(){busy=true;render();try{probe=await post('/v1/providers/probe',{provider:form.provider});if(probe.models?.length&&!form.model)form.model=probe.models[0];if(!probe.available)showNotice(probe.detail,'error')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function finishOnboarding(){saveVisible();busy=true;render();try{await post('/v1/onboarding/complete',{profile:{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType,autonomy_mode:form.autonomy,language:form.language,tone:form.tone,response_length:'medium',use_humor:false,salutation_style:'adaptive',email_signature:form.emailSignature},provider:form.provider,model:form.model||'default'});installed=true;await Promise.all([loadDashboard(true),loadRuntimeSettings(true)]);showNotice('MAIL-AGENT ist bereit.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}

function navItem(view,label,ico,badge='') { return `<button class="nav-item ${activeView===view?'active':''}" data-view="${view}">${icon(ico,19)}<span>${label}</span>${badge?`<b>${badge}</b>`:''}</button>`; }
function dashboardLayout(content) {
  const agentName=form.agentName||identity?.agent_name||'MAIL-AGENT';
  return `<main class="dashboard"><aside class="sidebar">${brand(true)}<nav>${navItem('overview','Übersicht','home')}${navItem('activity','Aktivität','spark',brainStatus?.pending_total||'')}${navItem('shadow','Testmodus','shield',runtimeSettings?.behavior?.execution_mode==='shadow'?'SHADOW':'')}${navItem('system','System','settings',systemHealth?.summary?.error||systemHealth?.summary?.warning||'')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}${navItem('approvals','Freigaben','shield',dashboard.approvals.length||'')}${navItem('drafts','Entwürfe','draft',dashboard.drafts.length||'')}${navItem('settings','Einstellungen','settings')}</nav><div class="sidebar-bottom"><div class="agent-mini"><span class="avatar">${esc(agentName.slice(0,1).toUpperCase())}</span><span><b>${esc(agentName)}</b><small><i></i> Aktiv</small></span></div></div></aside><section class="workspace"><header class="topbar"><div><span class="workspace-kicker">MAIL-AGENT</span><h1>${viewTitle()}</h1></div><div class="top-actions"><button class="btn secondary compact" id="sync-now">${icon('sync',16)}Synchronisieren</button><span class="status-pill"><i></i> Gateway online</span></div></header><div class="workspace-body">${content}</div></section></main>`;
}
function viewTitle(){return ({overview:'Übersicht',activity:'Agent Activity',shadow:'Shadow Test',system:'Systemzustand',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}
function metric(label,value,sub,ico){return `<div class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon(ico,18)}</span></div><strong>${esc(value)}</strong><small>${esc(sub)}</small></div>`;}

function emptyState(ico, title, text) { return `<div class="empty-state large">${icon(ico,30)}<b>${esc(title)}</b><span>${esc(text)}</span></div>`; }
function renderDashboard(){
  const mailbox=dashboard.mailboxes[0]; const sync=mailbox?.sync||{};
  let content='';
  if(activeView==='overview') content=`<section class="hero-card"><div><span class="hero-kicker">DEIN AGENT IST BEREIT</span><h2>${esc(form.agentName||'MAIL-AGENT')} hält dein Postfach im Blick.</h2><p>Neue Nachrichten werden lokal synchronisiert, analysiert und nur innerhalb deiner Regeln bearbeitet.</p><div class="hero-actions"><button class="btn primary" data-view="inbox">Inbox öffnen${icon('chevron',16)}</button><button class="btn secondary" data-view="approvals">Freigaben prüfen</button></div></div><div class="hero-orb">${icon('spark',38)}</div></section><div class="stats-grid">${metric('Postfach',mailbox?.email_address||'Nicht verbunden',mailbox?.credential_available?'Vault geschützt':'Credential fehlt','mail')}${metric('Inbox',dashboard.messages.length,'lokal geladene Nachrichten','inbox')}${metric('Freigaben',dashboard.approvals.length,'warten auf deine Entscheidung','shield')}${metric('Entwürfe',dashboard.drafts.length,'vom Agenten vorbereitet','draft')}</div><section class="panel"><div class="panel-head"><div><span>LETZTE NACHRICHTEN</span><h3>Inbox</h3></div><button class="link-btn" data-view="inbox">Alle anzeigen →</button></div>${dashboard.messages.length?dashboard.messages.slice(0,5).map(mailRow).join(''):'<div class="empty-state">Noch keine Nachrichten synchronisiert.</div>'}</section>`;
  if(activeView==='activity') content=renderActivityCenter();
  if(activeView==='shadow') content=renderShadowCenter();
  if(activeView==='system') content=renderSystemHealth();
  if(activeView==='inbox') content=`<section class="panel full"><div class="panel-head"><div><span>LOKAL SYNCHRONISIERT</span><h3>${esc(mailbox?.email_address||'Inbox')}</h3></div><span class="muted">${sync.last_synced_at?`Zuletzt ${esc(new Date(sync.last_synced_at).toLocaleString())}`:'Noch kein Sync'}</span></div>${dashboard.messages.length?dashboard.messages.map(mailRow).join(''):emptyState('inbox','Deine Inbox ist noch leer','Starte die erste Synchronisierung oben rechts.')}</section>`;
  if(activeView==='approvals') content=`<section class="panel full"><div class="panel-head"><div><span>HUMAN-IN-THE-LOOP</span><h3>Freigabe-Queue</h3></div><span class="badge">${dashboard.approvals.length} offen</span></div>${dashboard.approvals.length?dashboard.approvals.map(approvalCard).join(''):emptyState('shield','Alles erledigt','Es gibt aktuell keine offenen Aktionen.')}</section>`;
  if(activeView==='drafts') content=`<section class="panel full"><div class="panel-head"><div><span>VORBEREITET VON ${esc((form.agentName||'Agent').toUpperCase())}</span><h3>Entwürfe</h3></div><span class="badge">${dashboard.drafts.length}</span></div>${dashboard.drafts.length?dashboard.drafts.map(draftCard).join(''):emptyState('draft','Noch keine Entwürfe','Sobald dein Agent Antworten vorbereitet, erscheinen sie hier.')}</section>`;
  if(activeView==='settings') content=renderAgentSettings();
  app.innerHTML=dashboardLayout(content); if(activeView==='settings')renderUpdatePanel(); bindDashboard();
}
function mailRow(item){const preview=String(item.agent_summary||item.body_text||'').replace(/\s+/g,' ').slice(0,140);const priority=item.agent_priority||'';const category=item.agent_category||'';const intelligence=`<div class="intel-badges">${priority?`<span class="intel-badge ${esc(priority)}">${esc(priority)}</span>`:''}${category?`<span class="intel-badge">${esc(category)}</span>`:''}${item.needs_reply===true?'<span class="intel-badge">Antwort nötig</span>':''}</div>`;return `<article class="mail-row"><span class="mail-avatar">${esc((item.sender||'?').slice(0,1).toUpperCase())}</span><div class="mail-main"><div class="mail-line"><b>${esc(item.sender||'Unbekannt')}</b><span>${esc(item.sent_at?new Date(item.sent_at).toLocaleDateString():'')}</span></div><h4>${esc(item.subject||'(ohne Betreff)')}</h4>${intelligence}<p>${esc(preview)}${String(item.agent_summary||item.body_text||'').length>140?'…':''}</p></div><span class="row-arrow">${icon('chevron',17)}</span></article>`;}
function approvalCard(item){const p=item.proposal||{};const execution=item.execution_status||'';const failed=item.status==='approved'&&execution==='failed';const uncertain=item.status==='approved'&&execution==='uncertain';const ready=item.status==='approved'&&execution==='ready';const sends=['send_reply','forward'].includes(item.action);const status=uncertain?`<span class="delivery-failed">Versandstatus unklar · ${esc(item.execution_error||'Gesendet-Ordner prüfen')}</span>`:failed?`<span class="delivery-failed">Ausführung fehlgeschlagen · ${esc(item.execution_error||'erneut versuchen')}</span>`:ready?'<span>Erneuter Versuch freigegeben</span>':`<span>Risiko: ${esc(item.policy?.risk||'')}</span>`;const retryLabel=sends?'Erneut senden':'Erneut ausführen';const approveLabel=sends?'Freigeben & senden':'Freigeben & ausführen';let actions='';if(uncertain)actions=`<button class="btn secondary compact" data-reconcile-sent="${esc(item.approval_id)}">${icon('check',15)} Bereits gesendet</button><button class="btn primary compact" data-reconcile-retry="${esc(item.approval_id)}">${icon('sync',15)} Nicht gesendet</button>`;else if(failed||ready)actions=`<button class="btn primary compact" data-execute="${esc(item.approval_id)}">${icon('sync',15)} ${retryLabel}</button>`;else actions=`<button class="btn secondary compact" data-reject="${esc(item.approval_id)}">${icon('x',15)} Ablehnen</button><button class="btn primary compact" data-approve="${esc(item.approval_id)}">${icon('check',15)} ${approveLabel}</button>`;return `<article class="approval"><span class="risk-icon">${icon('shield',19)}</span><div class="approval-copy"><div class="mail-line"><b>${esc(item.action)}</b>${status}</div><h4>${esc(p.subject||p.destination_folder||p.recipient||'Mail-Aktion')}</h4><p>${uncertain?'MAIL-AGENT wurde während der Ausführung beendet. Prüfe zuerst den Gesendet-Ordner; ein automatischer Retry könnte die Mail doppelt senden.':esc(p.summary||p.reason||item.policy?.reason||'')}</p></div><div class="approval-actions">${actions}</div></article>`;}
function draftCard(item){
  const editable=item.status!=='sent';
  const editing=editingDraftId===item.draft_id;
  const proposal=item.proposal||{};
  const replyLocked=item.source_action==='send_reply'||proposal.metadata?.drafted_from_action==='send_reply';
  if(editing){return `<article class="draft-card draft-editor"><div class="draft-head"><span>${icon('draft',18)}</span><div><b>Entwurf bearbeiten</b><small>Revision ${esc(item.revision||1)} · beim Speichern wird neu signiert</small></div><span class="badge soft">${esc(item.status)}</span></div><div class="form-grid two"><label class="field"><span>Empfänger</span><input data-draft-recipient value="${esc(item.recipient||'')}" ${replyLocked?'disabled':''}></label><label class="field"><span>Betreff</span><input data-draft-subject value="${esc(item.subject||'')}"></label></div><label class="field"><span>Nachricht</span><textarea data-draft-body rows="10">${esc(item.editable_body||'')}</textarea></label><div class="security-note">${icon('shield',18)}<span>Der Agent-ID-Block ist absichtlich nicht editierbar. MAIL-AGENT erzeugt und signiert ihn nach dem Speichern neu.</span></div><div class="draft-actions"><button class="btn text compact" data-draft-cancel>Abbrechen</button><button class="btn primary compact" data-draft-save="${esc(item.draft_id)}">Speichern & neu signieren</button></div></article>`;}
  const submit=!item.approval_id&&editable?`<button class="btn primary compact" data-draft-submit="${esc(item.draft_id)}">${icon('shield',15)} Zur Freigabe</button>`:'';
  const edit=editable?`<button class="btn secondary compact" data-draft-edit="${esc(item.draft_id)}">Bearbeiten</button>`:'';
  return `<article class="draft-card"><div class="draft-head"><span>${icon('draft',18)}</span><div><b>${esc(item.subject||'(ohne Betreff)')}</b><small>An ${esc(item.recipient||'offen')} · Revision ${esc(item.revision||1)}</small></div><span class="badge soft">${esc(item.status)}</span></div><p>${esc(String(item.editable_body||item.body||'').slice(0,320))}${String(item.editable_body||item.body||'').length>320?'…':''}</p><div class="draft-actions">${edit}${submit}${item.approval_id?'<span class="muted">Freigabe offen</span>':''}</div></article>`;
}


function checked(value){return value?'checked':'';}
function ruleRow(rule,index){const mode=rule.mode||'normal',priority=rule.priority||'',category=rule.category||'';return `<div class="rule-row" data-rule-index="${index}"><input data-rule-field="pattern" value="${esc(rule.pattern||'')}" placeholder="@firma.de oder person@…"><select data-rule-field="mode"><option value="normal" ${mode==='normal'?'selected':''}>Normal</option><option value="analyze_only" ${mode==='analyze_only'?'selected':''}>Nur analysieren</option><option value="draft_only" ${mode==='draft_only'?'selected':''}>Nur Entwurf</option><option value="ignore" ${mode==='ignore'?'selected':''}>Ignorieren</option></select><select data-rule-field="priority"><option value="" ${!priority?'selected':''}>Priorität · automatisch</option><option value="urgent" ${priority==='urgent'?'selected':''}>Urgent</option><option value="high" ${priority==='high'?'selected':''}>High</option><option value="normal" ${priority==='normal'?'selected':''}>Normal</option><option value="low" ${priority==='low'?'selected':''}>Low</option></select><select data-rule-field="category"><option value="" ${!category?'selected':''}>Kategorie · automatisch</option>${['personal','work','finance','support','sales','newsletter','notification','security','other'].map(v=>`<option value="${v}" ${category===v?'selected':''}>${v}</option>`).join('')}</select><button class="btn text rule-remove" type="button" data-rule-remove="${index}" title="Regel entfernen">${icon('x',15)}</button></div>`;}
function collectRuleRows(){return [...document.querySelectorAll('.rule-row')].map(row=>{const read=field=>row.querySelector(`[data-rule-field="${field}"]`)?.value?.trim()||'';const priority=read('priority'),category=read('category');return {pattern:read('pattern'),mode:read('mode')||'normal',priority:priority||null,category:category||null};}).filter(rule=>rule.pattern);}
function brainActivityRow(event){
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

const activityStageLabels={queued:'Eingeplant',sync:'Synchronisierung',context:'Thread-Kontext',brain:'Brain-Kontext',llm:'LLM-Analyse',proposal:'Vorschlag',rule:'Regel',policy:'Policy Engine',artifact:'Aktion / Artefakt',finished:'Ergebnis'};
function activityOutcomeLabel(outcome=''){
  return ({draft_created:'Entwurf erstellt',approval_required:'Freigabe nötig',executed:'Ausgeführt',no_action:'Keine Aktion',blocked:'Blockiert',below_confidence:'Konfidenz zu niedrig',ignored:'Ignoriert',error:'Fehler',sync_completed:'Synchronisiert'})[outcome]||outcome||'Läuft';
}
function agentTraceCard(trace){
  const statusClass=trace.status==='failed'||trace.outcome==='error'?'bad':trace.status==='running'?'running':'ok';
  const title=trace.subject||'Postfach-Synchronisierung';
  const meta=[trace.sender,trace.provider&&trace.model?`${trace.provider} / ${trace.model}`:trace.provider].filter(Boolean).join(' · ');
  const steps=(trace.steps||[]).map(step=>{
    const duration=step.duration_ms!==null&&step.duration_ms!==undefined?` · ${Math.round(step.duration_ms)} ms`:'';
    const state=step.status==='failed'||step.status==='blocked'?'bad':step.status==='running'?'running':'ok';
    return `<div class="activity-step ${state}"><span class="activity-dot"></span><div><b>${esc(activityStageLabels[step.stage]||step.stage||'Schritt')}</b><small>${esc(step.detail||'')}${esc(duration)}</small></div></div>`;
  }).join('');
  return `<article class="activity-trace"><div class="activity-trace-head"><div><span class="activity-time">${esc(trace.started_at?new Date(trace.started_at).toLocaleString():'')}</span><h4>${esc(title)}</h4><p>${esc(meta)}</p></div><span class="activity-outcome ${statusClass}">${esc(activityOutcomeLabel(trace.outcome))}</span></div>${steps}<div class="activity-why"><b>Warum?</b><span>${esc(trace.reason||'Der Lauf ist noch nicht abgeschlossen.')}</span></div></article>`;
}
function renderActivityCenter(){
  const brain=brainStatus||{};
  const summary=brain.activity_summary||{};
  const traces=brain.activity||[];
  const pending=Number(brain.pending_total||0);
  const avg=summary.avg_llm_ms===null||summary.avg_llm_ms===undefined?'—':`${Math.round(summary.avg_llm_ms)} ms`;
  const failures=Number(summary.failed||0);
  const running=Number(summary.running||0);
  return `<div class="activity-center">
    <section class="activity-hero panel"><div><span class="hero-kicker">LOCAL AGENT OBSERVABILITY</span><h2>Was der Agent tut – und warum.</h2><p>Jeder Schritt bleibt lokal nachvollziehbar. Mailtexte, Prompts, SOUL/MEMORY-Inhalte und Zugangsdaten werden nicht in Activity-Traces gespeichert.</p><div class="hero-actions"><button class="btn primary" id="activity-run-agent">Agent jetzt arbeiten lassen</button><button class="btn secondary" id="activity-refresh">Aktualisieren</button></div></div><div class="hero-orb">${icon('spark',34)}</div></section>
    <div class="stats-grid">${metric('Backlog',pending,'Mails warten auf Analyse','inbox')}${metric('Traces',summary.trace_count||0,'zuletzt protokollierte Mail-Läufe','spark')}${metric('LLM Ø',avg,'gemessene Analysezeit','sync')}${metric('Fehler',failures,running?`${running} Lauf/Läufe aktiv`:'keine laufenden Traces','shield')}</div>
    <section class="panel full"><div class="panel-head"><div><span>ENTSCHEIDUNGS-TIMELINE</span><h3>Letzte Agentenläufe</h3></div><span class="badge ${pending?'':'soft'}">${esc(pending)} WARTEN</span></div>${traces.length?traces.map(agentTraceCard).join(''):emptyState('spark','Noch keine Traces','Synchronisiere dein Postfach oder starte den Agenten. Jeder neue Lauf erscheint dann hier.')}</section>
  </div>`;
}

function shadowOutcomeLabel(value=''){
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

function healthStatusLabel(value){return ({ok:'Bereit',warning:'Warnung',error:'Aktion nötig'})[value]||value||'Unbekannt';}
function healthActionButton(check){
  if(!check.action)return '';
  const labels={retry_sync:'Sync erneut versuchen',open_llm_settings:'LLM-Einstellungen öffnen',open_approvals:'Freigaben öffnen',review_uncertain:'Versandstatus prüfen',reconnect_mailbox:'Postfach neu verbinden',open_mailbox_setup:'Postfach einrichten',open_logs:'Diagnose anzeigen',restart_onboarding:'Einrichtung prüfen'};
  return `<button class="btn secondary compact" data-health-action="${esc(check.action)}" data-health-mailbox="${esc(check.data?.mailbox_id||'')}">${esc(labels[check.action]||'Öffnen')}</button>`;
}
function renderSystemHealth(){
  const health=systemHealth||{};
  const summary=health.summary||{};
  const checks=health.checks||[];
  const overall=health.overall||'checking';
  const headline=overall==='ok'?'Alles bereit':overall==='degraded'?'System läuft mit Hinweisen':'Aktion erforderlich';
  const detail=overall==='ok'?'Gateway, lokaler Speicher, Datenbank, Agentenidentität, Postfach und LLM sind bereit.':overall==='degraded'?'MAIL-AGENT läuft weiter, aber mindestens ein Bereich sollte geprüft werden.':'Mindestens ein Problem braucht deine Entscheidung oder erneute Verbindung.';
  return `<div class="system-center"><section class="panel activity-hero"><div><span class="hero-kicker">RELIABILITY & RECOVERY</span><h2>${esc(headline)}</h2><p>${esc(detail)}</p><div class="hero-actions"><button class="btn primary" id="system-health-refresh" ${systemHealthLoading?'disabled':''}>${systemHealthLoading?'Prüfe …':'System prüfen'}</button></div></div><div class="hero-orb">${icon(overall==='ok'?'check':'shield',34)}</div></section><div class="stats-grid">${metric('Bereit',summary.ok||0,'erfolgreiche Prüfungen','check')}${metric('Warnungen',summary.warning||0,'weiterhin funktionsfähig','sync')}${metric('Fehler',summary.error||0,'brauchen Aufmerksamkeit','shield')}${metric('Geprüft',health.checked_at?new Date(health.checked_at).toLocaleTimeString():'—','lokale Selbstdiagnose','settings')}</div><section class="panel full"><div class="panel-head"><div><span>SELBSTDIAGNOSE</span><h3>Komponenten & Recovery</h3></div><span class="badge ${overall==='ok'?'soft':''}">${esc(overall.toUpperCase())}</span></div>${checks.length?checks.map(check=>`<div class="security-block health-check ${esc(check.status||'')}"><span>${icon(check.status==='ok'?'check':check.status==='warning'?'sync':'shield',22)}</span><div><b>${esc(check.id||'Prüfung')} · ${esc(healthStatusLabel(check.status))}</b><p>${esc(check.detail||'')}</p>${healthActionButton(check)}</div></div>`).join(''):emptyState('settings','Noch nicht geprüft','Starte die lokale Selbstdiagnose.')}</section><section class="panel full"><div class="security-note">${icon('shield',18)}<span>Nach einem Absturz während Send/Forward versucht MAIL-AGENT niemals automatisch erneut zu senden. Ein unklarer Versandstatus muss zuerst von dir abgeglichen werden.</span></div></section></div>`;
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

function brainLearningCard(item){return `<div class="security-block"><span>${icon('spark',22)}</span><div><b>${esc(item.title||'Lernvorschlag')}</b><p>${esc(item.reason||'')}</p><small>${esc(item.memory_line||'')}</small><div class="inline-actions left"><button class="btn secondary compact" data-learning-reject="${esc(item.candidate_id)}">Verwerfen</button><button class="btn primary compact" data-learning-accept="${esc(item.candidate_id)}">Übernehmen</button></div></div></div>`;}
function renderAgentSettings(){
  const rs=runtimeSettings||{};
  const id=rs.identity||identity||{};
  const profile=rs.profile||{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType,autonomy_mode:form.autonomy,language:form.language,tone:form.tone,email_signature:form.emailSignature};
  const behavior=rs.behavior||{enabled:true,execution_mode:'live',auto_analyze_new_mail:true,auto_create_drafts:true,minimum_confidence:.72,max_messages_per_cycle:20,thread_context_messages:8,active_days:[0,1,2,3,4,5,6],active_from:'00:00',active_until:'23:59',never_auto_act_senders:[],rules:[]};
  const provider=rs.provider||form.provider||'ollama';
  const catalog=rs.providers||{};
  const models=catalog[provider]?.models||[];
  const model=rs.model||form.model||'default';
  const modelControl=provider==='ollama'&&models.length
    ? `<label class="field"><span>Modell</span><select id="settings-model">${models.map(m=>`<option value="${esc(m)}" ${m===model?'selected':''}>${esc(m)}</option>`).join('')}</select></label>`
    : `<label class="field"><span>Modell</span><input id="settings-model" value="${esc(model)}" placeholder="default oder Modell-ID"></label>`;
  const days=[['Mo',0],['Di',1],['Mi',2],['Do',3],['Fr',4],['Sa',5],['So',6]].map(([label,day])=>`<label class="day-chip"><input type="checkbox" data-agent-day="${day}" ${checked((behavior.active_days||[]).includes(day))}><span>${label}</span></label>`).join('');
  const providerDetail=settingsProbe?.provider===provider?settingsProbe.detail:(catalog[provider]?.detail||'Noch nicht geprüft');
  const ruleRows=(behavior.rules||[]).map(ruleRow).join('');
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
  return `<div class="settings-grid agent-settings-grid">
    <section class="panel"><div class="panel-head"><div><span>AGENTEN-IDENTITÄT</span><h3>${esc(id.agent_name||form.agentName||'MAIL-AGENT')}</h3></div><span class="badge soft">UNVERÄNDERLICH</span></div><div class="setting-row"><span>Agent-ID</span><b class="mono">${esc(id.agent_id||'—')}</b></div><div class="setting-row"><span>Fingerprint</span><b class="mono small-mono">${esc(id.fingerprint||'—')}</b></div><div class="security-block">${icon('shield',22)}<div><b>Identifikation ist zwingend</b><p>Jeder vom Agenten erzeugte Entwurf, jede Antwort und jede Weiterleitung erhält automatisch Agent-ID und Fingerprint. Diese Pflicht kann weder vom Modell noch in den Einstellungen abgeschaltet werden.</p></div></div></section>
    ${brainPanels}
    <section class="panel"><div class="panel-head"><div><span>LLM</span><h3>Modell jederzeit wechseln</h3></div><span class="badge soft">${esc(provider)}</span></div><div class="form-grid two"><label class="field"><span>Provider</span><select id="settings-provider"><option value="ollama" ${provider==='ollama'?'selected':''}>Ollama · lokal</option><option value="codex" ${provider==='codex'?'selected':''}>ChatGPT / OpenAI · Browser-Login</option></select></label>${modelControl}</div><div class="security-block">${icon('spark',22)}<div><b>${catalog[provider]?.available?'Provider bereit':'Provider prüfen'}</b><p>${esc(providerDetail)}</p></div></div><div class="inline-actions left"><button class="btn secondary" id="settings-provider-test">Provider prüfen</button>${provider==='codex'?'<button class="btn secondary" id="settings-chatgpt-login">Mit ChatGPT anmelden</button>':''}<button class="btn primary" id="settings-save-llm">LLM speichern</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>PERSÖNLICHKEIT</span><h3>Antwortstil & Kontrolle</h3></div></div><div class="form-grid two"><label class="field"><span>Autonomie</span><select id="settings-autonomy"><option value="observer" ${profile.autonomy_mode==='observer'?'selected':''}>Observer</option><option value="assistant" ${profile.autonomy_mode==='assistant'?'selected':''}>Assistant</option><option value="copilot" ${profile.autonomy_mode==='copilot'?'selected':''}>Copilot</option><option value="autonomous" ${profile.autonomy_mode==='autonomous'?'selected':''}>Autonomous</option></select></label><label class="field"><span>Ton</span><select id="settings-tone"><option value="friendly" ${profile.tone==='friendly'?'selected':''}>Freundlich</option><option value="professional" ${profile.tone==='professional'?'selected':''}>Professionell</option><option value="direct" ${profile.tone==='direct'?'selected':''}>Direkt</option><option value="warm" ${profile.tone==='warm'?'selected':''}>Warm</option></select></label><label class="field"><span>Sprache</span><select id="settings-language"><option value="de" ${profile.language==='de'?'selected':''}>Deutsch</option><option value="en" ${profile.language==='en'?'selected':''}>English</option></select></label></div><label class="field"><span>Persönliche Signatur vor der Agent-ID</span><textarea id="settings-email-signature" rows="4">${esc(profile.email_signature||'')}</textarea></label><div class="security-note">${icon('lock',18)}<span>Die persönliche Signatur ist frei änderbar. Die darunter liegende MAIL-AGENT-ID-Signatur ist technisch verpflichtend.</span></div><div class="inline-actions left"><button class="btn primary" id="settings-save-profile">Profil speichern</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>AGENTISCHES VERHALTEN</span><h3>Wann und wie der Agent arbeitet</h3></div><span class="badge ${behavior.enabled?'':'soft'}">${behavior.enabled?'AKTIV':'PAUSIERT'}</span></div><div class="setting-row"><span>Agent aktiv</span><input id="behavior-enabled" type="checkbox" ${checked(behavior.enabled)}></div><label class="field"><span>Ausführungsmodus</span><select id="behavior-execution-mode"><option value="live" ${behavior.execution_mode!=='shadow'?'selected':''}>Live · Policy-gesteuert</option><option value="shadow" ${behavior.execution_mode==='shadow'?'selected':''}>Shadow · nur simulieren</option></select></label><div class="setting-row"><span>Neue Mails automatisch analysieren</span><input id="behavior-auto-analyze" type="checkbox" ${checked(behavior.auto_analyze_new_mail)}></div><div class="setting-row"><span>Antwortentwürfe automatisch vorbereiten</span><input id="behavior-auto-drafts" type="checkbox" ${checked(behavior.auto_create_drafts)}></div><div class="form-grid two"><label class="field"><span>Mindest-Konfidenz</span><input id="behavior-confidence" type="number" min="0" max="1" step="0.01" value="${esc(behavior.minimum_confidence)}"></label><label class="field"><span>Max. Mails pro Zyklus</span><input id="behavior-max-messages" type="number" min="1" max="200" value="${esc(behavior.max_messages_per_cycle)}"></label><label class="field"><span>Aktiv ab</span><input id="behavior-from" type="time" value="${esc(behavior.active_from)}"></label><label class="field"><span>Aktiv bis</span><input id="behavior-until" type="time" value="${esc(behavior.active_until)}"></label></div><div class="field"><span>Aktive Tage</span><div class="day-selector">${days}</div></div><label class="field"><span>Nie automatisch bearbeiten · Absender/Domain, eine Zeile pro Regel</span><textarea id="behavior-blocked-senders" rows="4" placeholder="newsletter@example.com\n@example.org">${esc((behavior.never_auto_act_senders||[]).join('\n'))}</textarea></label><div class="security-block">${icon('shield',22)}<div><b>Versand bleibt menschlich freigabepflichtig</b><p>Agentisch bedeutet: automatisch erkennen, analysieren und signierte Entwürfe vorbereiten. Senden, Weiterleiten und Löschen bleiben als High-Risk-Aktionen freigabepflichtig.</p></div></div><div class="inline-actions left"><button class="btn primary" id="settings-save-behavior">Verhalten speichern</button><button class="btn secondary" id="settings-run-agent">Agent jetzt ausführen</button></div></section>
    <section class="panel"><div class="panel-head"><div><span>REGELN</span><h3>Absender & Domains deterministisch steuern</h3></div><button class="btn secondary compact" id="settings-add-rule">Regel hinzufügen</button></div><p class="rule-help">Regeln werden nach der LLM-Analyse im Gateway erzwungen. Muster wie <b>@firma.de</b> oder eine vollständige Adresse sind möglich. „Nur Entwurf“ kann einen vorgeschlagenen Versand technisch auf einen Draft herunterstufen.</p><div class="rule-editor">${ruleRows||'<div class="empty-state">Noch keine speziellen Regeln.</div>'}</div><div class="security-note">${icon('shield',18)}<span>Priorität und Kategorie können pro Regel fest vorgegeben werden; leer bedeutet automatische Klassifikation.</span></div></section>
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
async function loadBrainStatus(silent=false){
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
  const behavior={...current,enabled:!!document.getElementById('behavior-enabled')?.checked,execution_mode:document.getElementById('behavior-execution-mode')?.value||current.execution_mode||'live',auto_analyze_new_mail:!!document.getElementById('behavior-auto-analyze')?.checked,auto_create_drafts:!!document.getElementById('behavior-auto-drafts')?.checked,minimum_confidence:Number(document.getElementById('behavior-confidence')?.value||0.72),max_messages_per_cycle:Number(document.getElementById('behavior-max-messages')?.value||20),active_from:document.getElementById('behavior-from')?.value||'00:00',active_until:document.getElementById('behavior-until')?.value||'23:59',active_days:days,never_auto_act_senders:blocked,rules:collectRuleRows()};
  try{runtimeSettings=await put('/v1/settings/behavior',{behavior});showNotice('Agentisches Verhalten gespeichert.');render();}
  catch(e){showNotice(e.message,'error');}
}
function addRule(){if(!runtimeSettings)return;const rules=collectRuleRows();rules.push({pattern:'',mode:'normal',priority:null,category:null});runtimeSettings.behavior={...(runtimeSettings.behavior||{}),rules};render();setTimeout(()=>document.querySelector('.rule-row:last-child input')?.focus(),0);}
function removeRule(index){if(!runtimeSettings)return;const rules=collectRuleRows();rules.splice(Number(index),1);runtimeSettings.behavior={...(runtimeSettings.behavior||{}),rules};render();}

async function runAgentNow(){
  const mailbox=dashboard.mailboxes[0];
  try{
    const result=await post('/v1/agent/run',{mailbox_id:mailbox?.mailbox_id||null,force:true});
    await Promise.all([loadDashboard(true),loadBrainStatus(true)]);
    const cycles=result.results||[];
    const total=key=>cycles.reduce((sum,item)=>sum+Number(item[key]||0),0);
    const pending=cycles.reduce((sum,item)=>sum+Number(item.pending_after||0),0);
    const shadow=cycles.some(item=>item.execution_mode==='shadow');
    if(shadow)showNotice(`Shadow-Lauf · ${total('processed')} analysiert · ${total('would_draft')} Entwürfe simuliert · ${total('would_approval')} Freigaben simuliert · ${total('errors')} Fehler · 0 Side Effects`);
    else showNotice(`Agentenlauf · ${total('processed')} verarbeitet · ${total('drafts')} Entwürfe · ${total('approvals')} Freigaben · ${total('errors')} Fehler · ${pending} warten`);
    render();
  }catch(e){showNotice(e.message,'error');}
}

function renderUpdatePanel(){
  const grid=document.querySelector('.settings-grid');
  if(!grid)return;
  const current=updateStatus?.current_version||'0.17.3';
  const available=!!updateStatus?.available;
  const error=updateStatus?.error||'';
  const headline=available?`Version ${esc(updateStatus.latest_version)} verfügbar`:error?'Update-Kanal nicht erreichbar':'Du bist auf dem neuesten Stand';
  const detail=error?esc(error):available?'Der Installer wird über HTTPS geladen, per SHA-256 geprüft und über die bestehende Installation installiert.':'MAIL-AGENT prüft im Hintergrund automatisch auf neue Releases.';
  grid.insertAdjacentHTML('beforeend',`<section class="panel update-panel"><div class="panel-head"><div><span>SOFTWARE & UPDATES</span><h3>MAIL-AGENT aktualisieren</h3></div><span class="badge soft">v${esc(current)}</span></div><div class="setting-row"><span>Installierte Version</span><b>${esc(current)}</b></div><div class="setting-row"><span>Update-Kanal</span><b>${esc(updateStatus?.channel||'Preview')}</b></div><div class="setting-row"><span>Automatische Prüfung</span><b>${updateStatus?.automatic_checks===false?'Aus':'Aktiv · alle 6 Stunden'}</b></div><div class="security-block">${icon('sync',22)}<div><b>${headline}</b><p>${detail}</p></div></div><div class="inline-actions left"><button class="btn secondary" id="check-update" ${updateLoading?'disabled':''}>${updateLoading?'Prüfe …':'Jetzt nach Updates suchen'}</button>${available?'<button class="btn primary" id="install-update">Update installieren</button>':''}${error?'<button class="btn text" id="open-release">Release-Seite öffnen</button>':''}</div><div class="security-note">${icon('shield',18)}<span>Updates ersetzen nur Programmdateien. Identität, Gmail-Tokens, Einstellungen und lokale Mail-Daten bleiben erhalten.</span></div></section>`);
  if(!updateStatus&&!updateLoading)setTimeout(()=>checkUpdate(true),0);
}
async function checkUpdate(silent=false){
  if(updateLoading)return;
  updateLoading=true;
  if(activeView==='settings')render();
  try{
    updateStatus=await get('/v1/system/update');
    if(!silent){
      if(updateStatus.available)showNotice(`MAIL-AGENT ${updateStatus.latest_version} ist verfügbar.`);
      else if(updateStatus.error)showNotice('Automatischer Update-Kanal momentan nicht erreichbar.','error');
      else showNotice('MAIL-AGENT ist aktuell.');
    }
  }catch(e){showNotice(e.message,'error');}
  finally{updateLoading=false;if(activeView==='settings')render();}
}
async function installUpdate(){
  try{
    const result=await post('/v1/system/update/install',{});
    if(result.installing)showNotice('Update wird installiert. MAIL-AGENT startet anschließend automatisch neu.');
    else showNotice('MAIL-AGENT ist bereits aktuell.');
  }catch(e){showNotice(e.message,'error');}
}
document.addEventListener('click',event=>{
  const button=event.target.closest('#check-update,#install-update,#open-release');
  if(!button)return;
  if(button.id==='check-update')checkUpdate(false);
  if(button.id==='install-update')installUpdate();
  if(button.id==='open-release')window.open(updateStatus?.release_page||'https://github.com/TimeLance89/Mail-Agent/releases/tag/preview-latest','_blank');
});

function bindDashboard(){
  document.querySelectorAll('[data-view]').forEach(el=>el.onclick=async()=>{activeView=el.dataset.view;if(['settings','activity','shadow','system'].includes(activeView))await Promise.all([runtimeSettings?Promise.resolve():loadRuntimeSettings(true),loadBrainStatus(true),activeView==='shadow'?loadShadowStatus(true):Promise.resolve(),activeView==='system'?loadSystemHealth(true):Promise.resolve()]);render();});
  document.getElementById('sync-now')?.addEventListener('click',syncNow);
  document.querySelectorAll('[data-approve]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.approve,'approve'));
  document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));
  document.querySelectorAll('[data-execute]').forEach(el=>el.onclick=()=>retryApproval(el.dataset.execute));
  document.querySelectorAll('[data-reconcile-sent]').forEach(el=>el.onclick=()=>reconcileApproval(el.dataset.reconcileSent,'already_sent'));
  document.querySelectorAll('[data-reconcile-retry]').forEach(el=>el.onclick=()=>reconcileApproval(el.dataset.reconcileRetry,'retry'));
  document.getElementById('system-health-refresh')?.addEventListener('click',async()=>{await loadSystemHealth(false);render();});
  document.querySelectorAll('[data-health-action]').forEach(el=>el.onclick=()=>handleHealthAction(el.dataset.healthAction,el.dataset.healthMailbox));
  document.querySelectorAll('[data-draft-edit]').forEach(el=>el.onclick=()=>{editingDraftId=el.dataset.draftEdit;render();});
  document.querySelectorAll('[data-draft-cancel]').forEach(el=>el.onclick=()=>{editingDraftId=null;render();});
  document.querySelectorAll('[data-draft-save]').forEach(el=>el.onclick=()=>saveDraft(el.dataset.draftSave));
  document.querySelectorAll('[data-draft-submit]').forEach(el=>el.onclick=()=>submitDraft(el.dataset.draftSubmit));
  document.getElementById('settings-provider-test')?.addEventListener('click',probeSettingsProvider);
  document.getElementById('settings-chatgpt-login')?.addEventListener('click',startChatGptLogin);
  document.getElementById('settings-save-llm')?.addEventListener('click',saveLlmSettings);
  document.getElementById('settings-save-profile')?.addEventListener('click',saveProfileSettings);
  document.getElementById('settings-save-behavior')?.addEventListener('click',saveBehaviorSettings);
  document.getElementById('settings-run-agent')?.addEventListener('click',runAgentNow);
  document.getElementById('brain-run-agent')?.addEventListener('click',runAgentNow);
  document.getElementById('settings-save-brain')?.addEventListener('click',saveBrainSettings);
  document.getElementById('settings-refresh-brain')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});
  document.getElementById('brain-refresh-activity')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});
  document.getElementById('activity-run-agent')?.addEventListener('click',runAgentNow);
  document.getElementById('activity-refresh')?.addEventListener('click',async()=>{await loadBrainStatus(false);render();});
  document.getElementById('shadow-enable')?.addEventListener('click',()=>setExecutionMode('shadow'));
  document.getElementById('shadow-disable')?.addEventListener('click',()=>setExecutionMode('live'));
  document.getElementById('shadow-refresh')?.addEventListener('click',async()=>{await loadShadowStatus(false);render();});
  document.getElementById('shadow-replay')?.addEventListener('click',startShadowReplay);
  document.getElementById('rule-simulate')?.addEventListener('click',simulateRule);
  document.querySelectorAll('[data-learning-accept]').forEach(el=>el.onclick=()=>decideBrainLearning(el.dataset.learningAccept,'accept'));
  document.querySelectorAll('[data-learning-reject]').forEach(el=>el.onclick=()=>decideBrainLearning(el.dataset.learningReject,'reject'));
  document.getElementById('settings-add-rule')?.addEventListener('click',addRule);
  document.querySelectorAll('[data-rule-remove]').forEach(el=>el.onclick=()=>removeRule(el.dataset.ruleRemove));
  document.getElementById('settings-provider')?.addEventListener('change',event=>{if(!runtimeSettings)return;runtimeSettings.provider=event.target.value;runtimeSettings.model=event.target.value==='codex'?'default':(runtimeSettings.providers?.[event.target.value]?.models?.[0]||'');settingsProbe=null;render();});
}
async function loadDashboard(silent=false){if(!silent)busy=true;try{const mb=await get('/v1/mailboxes');dashboard.mailboxes=mb.mailboxes||[];dashboard.approvals=(await get('/v1/approvals?status=attention&limit=50')).approvals||[];dashboard.drafts=(await get('/v1/drafts?limit=50')).drafts||[];const active=dashboard.mailboxes[0];dashboard.messages=active?(await get(`/v1/mailboxes/${encodeURIComponent(active.mailbox_id)}/messages?limit=50`)).messages||[]:[];}catch(e){showNotice(e.message,'error')}finally{busy=false;}}
async function syncNow(){const mb=dashboard.mailboxes[0];if(!mb)return;busy=true;render();try{await post('/v1/sync/run',{mailbox_id:mb.mailbox_id,limit:100});await Promise.all([loadDashboard(true),loadBrainStatus(true)]);showNotice('Postfach ist aktuell. Agentenstatus wurde aktualisiert.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function decideApproval(id,decision){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);const done=result.execution_status==='sent'?'Freigegeben und gesendet.':result.execution_status==='completed'?'Freigegeben und ausgeführt.':'Aktion freigegeben.';showNotice(decision==='approve'?done:'Aktion abgelehnt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}
async function retryApproval(id){try{const result=await post(`/v1/approvals/${encodeURIComponent(id)}/execute`,{});await loadDashboard(true);showNotice(result.execution_status==='sent'?'Nachricht wurde gesendet.':'Aktion wurde ausgeführt.');render();}catch(e){await loadDashboard(true);showNotice(e.message,'error');render();}}
async function saveDraft(id){const card=document.querySelector('.draft-editor');if(!card)return;const body=card.querySelector('[data-draft-body]')?.value||'';const subject=card.querySelector('[data-draft-subject]')?.value||'';const recipient=card.querySelector('[data-draft-recipient]')?.value||null;try{await put(`/v1/drafts/${encodeURIComponent(id)}`,{subject,body,recipient,actor:'local-user'});editingDraftId=null;await Promise.all([loadDashboard(true),loadBrainStatus(true)]);showNotice('Entwurf gespeichert, neu signiert und als Besitzer-Feedback berücksichtigt.');render();}catch(e){showNotice(e.message,'error');}}
async function submitDraft(id){try{await post(`/v1/drafts/${encodeURIComponent(id)}/submit`,{actor:'local-user'});await loadDashboard(true);showNotice('Entwurf wartet jetzt auf Freigabe.');render();}catch(e){showNotice(e.message,'error');}}
function render(){installed?renderDashboard():renderSetup();}
async function boot(){try{const [status,oauth]=await Promise.all([get('/v1/onboarding/status'),get('/v1/oauth/providers').catch(()=>({google:{configured:false}}))]);oauthProviders=oauth||oauthProviders;if(status.identity){identity=status.identity;form.ownerId=identity.owner_id||'';form.agentName=identity.agent_name||'Nova';form.usageType=identity.usage_type||'private';}const mb=status.mailboxes?.[0]||status.mailbox;if(mb){mailboxConnected=true;mailboxId=mb.mailbox_id;mailboxConnector=mb.connector||'imap';form.emailAddress=mb.email_address||'';form.mailboxUsername=mb.username||'';form.imapHost=mb.imap_host||'';form.imapPort=mb.imap_port||993;form.smtpHost=mb.smtp_host||'';form.smtpPort=mb.smtp_port||465;}if(status.configuration){const c=status.configuration,p=c.profile||{};form.provider=c.provider||form.provider;form.model=c.model||form.model;form.autonomy=p.autonomy_mode||form.autonomy;form.language=p.language||form.language;form.tone=p.tone||form.tone;form.emailSignature=p.email_signature||'';}installed=!!status.completed;if(installed)await Promise.all([loadDashboard(true),loadRuntimeSettings(true),loadBrainStatus(true),loadSystemHealth(true)]);}catch(e){showNotice(`Gateway nicht bereit: ${e.message}`,'error')}render();}
boot();
