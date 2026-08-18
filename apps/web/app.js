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
let mailboxConnector = null;
let oauthProviders = { google: { configured: false } };
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

function brand(compact=false) {
  return `<div class="brand ${compact?'compact':''}"><div class="brand-logo">${icon('mail',22)}</div><div><strong>MAIL<span>·</span>AGENT</strong>${compact?'':'<small>Private email intelligence</small>'}</div></div>`;
}
function stepper() {
  return `<div class="setup-stepper">${onboardingSteps.map((label, i) => `<div class="setup-dot ${i < step ? 'done' : ''} ${i === step ? 'active' : ''}"><span>${i < step ? icon('check',13) : i+1}</span><small>${label}</small></div>`).join('')}</div>`;
}
function setupLayout(content) {
  return `<main class="setup-page"><section class="setup-aside">${brand()}<div class="setup-aside-copy"><span class="kicker">SETUP IN WENIGEN MINUTEN</span><h1>Dein Postfach.<br><em>Dein Agent.</em></h1><p>MAIL-AGENT arbeitet lokal, kontrolliert und ausschließlich für E-Mail.</p></div><div class="trust-pill">${icon('shield',18)}<span><b>Local-first</b><small>Schlüssel und Mail-Zugang bleiben bei dir.</small></span></div></section><section class="setup-main"><div class="setup-top"><span>Schritt ${step+1} von ${onboardingSteps.length}</span><b>${onboardingSteps[step]}</b></div>${stepper()}<div class="setup-card">${content}</div><div class="setup-foot">MAIL-AGENT v0.3.0 · Lokales Gateway</div></section></main>`;
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
    const gmailConnected=mailboxConnected&&mailboxConnector==='gmail_api';
    body = `<div class="card-heading"><span class="card-icon">${icon('inbox',22)}</span><div><h2>Postfach verbinden</h2><p>Bei Gmail reicht eine normale Google-Anmeldung. Kein IMAP-Server und kein App-Passwort nötig.</p></div></div><div class="oauth-grid"><button class="oauth-card ${google.configured?'':'unavailable'}" id="google-connect" data-configured="${google.configured?'1':'0'}" ${busy?'disabled':''}><span class="google-mark">G</span><span><b>${gmailConnected?'Gmail verbunden':'Mit Google anmelden'}</b><small>${gmailConnected?esc(form.emailAddress):google.configured?'Sicher über Google OAuth 2.0 + PKCE':'Google OAuth ist in diesem Build noch nicht konfiguriert'}</small></span><span class="oauth-arrow">${gmailConnected?icon('check',17):icon('chevron',17)}</span></button><button class="oauth-card unavailable" type="button"><span class="ms-mark">M</span><span><b>Microsoft 365</b><small>OAuth-Anmeldung folgt als nächster Connector.</small></span></button></div>${gmailConnected?`<div class="success-line">${icon('check',16)} ${esc(form.emailAddress)} ist sicher über Gmail API verbunden.</div>`:''}<div class="separator"><span>oder manuell per IMAP / SMTP</span></div><div class="form-grid two">${field('E-Mail-Adresse','email-address',form.emailAddress,'email','name@example.com')}${field('Benutzername','mailbox-username',form.mailboxUsername,'text','meist E-Mail-Adresse')}${field('IMAP-Server','imap-host',form.imapHost,'text','imap.example.com')}${field('IMAP-Port','imap-port',form.imapPort,'number')}${field('SMTP-Server','smtp-host',form.smtpHost,'text','smtp.example.com')}${field('SMTP-Port','smtp-port',form.smtpPort,'number')}</div>${field('Passwort / App-Passwort','mailbox-password',form.mailboxPassword,'password','••••••••••••')}<div class="security-note">${icon('lock',18)}<span>Google-Tokens und manuelle Mail-Secrets werden ausschließlich verschlüsselt im lokalen Vault gespeichert.</span></div><div class="setup-actions"><button class="btn text" data-back="1">Zurück</button><div class="inline-actions"><button class="btn secondary" id="mailbox-test" ${busy?'disabled':''}>IMAP testen</button><button class="btn primary" id="next" ${!mailboxConnected?'disabled':''}>Weiter${icon('chevron',17)}</button></div></div>`;
  }
  if (step===3) { const models=probe?.models||[]; body=`<div class="card-heading"><span class="card-icon">${icon('spark',22)}</span><div><h2>Welches Modell soll denken?</h2><p>Du kannst lokal mit Ollama oder über deinen angemeldeten Codex-Client arbeiten.</p></div></div><div class="selection-grid two">${choice('provider','ollama','Ollama','Komplett lokal. Ideal für maximale Privatsphäre.',form.provider==='ollama','home')}${choice('provider','codex','ChatGPT / Codex','Nutzt den lokal angemeldeten Codex-Client.',form.provider==='codex','spark')}</div><div class="inline-actions left"><button class="btn secondary" id="provider-test" ${busy?'disabled':''}>Provider prüfen</button>${probe?`<span class="probe ${probe.available?'ok':'bad'}">${probe.available?'Bereit':'Nicht verfügbar'}</span>`:''}</div>${models.length?selectField('Modell','model-select',models.map(m=>[m,m]),form.model):''}${actions(2,'Weiter','next',!probe?.available)}`; }
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
  document.getElementById('mailbox-test')?.addEventListener('click',probeMailbox);
  document.getElementById('provider-test')?.addEventListener('click',probeProvider);
  document.getElementById('finish')?.addEventListener('click',finishOnboarding);
}
async function createIdentity(){saveVisible();busy=true;render();try{identity=await post('/v1/onboarding/identity',{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType});step=2;}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function probeMailbox(){saveVisible();busy=true;render();try{const r=await post('/v1/mailboxes/probe',{email_address:form.emailAddress,username:form.mailboxUsername,password:form.mailboxPassword,imap_host:form.imapHost,imap_port:form.imapPort,smtp_host:form.smtpHost,smtp_port:form.smtpPort});mailboxConnected=true;mailboxId=r.mailbox_id;mailboxConnector='imap';form.mailboxPassword='';showNotice('Postfach sicher verbunden.')}catch(e){mailboxConnected=false;showNotice(e.message,'error')}finally{busy=false;render()}}

async function connectGoogle(){
  saveVisible();
  const configured=document.getElementById('google-connect')?.dataset.configured==='1';
  if(!configured){showNotice('Google OAuth ist für diesen Build noch nicht freigeschaltet. Der Projekt-Client muss einmalig konfiguriert werden.','error');return;}
  const popup=window.open('about:blank','mail-agent-google','popup=yes,width=560,height=760');
  if(!popup){showNotice('Der Browser hat das Google-Anmeldefenster blockiert. Pop-ups für MAIL-AGENT erlauben.','error');return;}
  busy=true;render();
  try{
    const start=await post('/v1/oauth/google/start',{login_hint:form.emailAddress||null});
    popup.location.replace(start.authorization_url);
    const result=await waitForOAuth(start.state,popup);
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

async function waitForOAuth(state,popup){
  const deadline=Date.now()+5*60*1000;
  while(Date.now()<deadline){
    const session=await get(`/v1/oauth/sessions/${encodeURIComponent(state)}`);
    if(session.status==='complete'){try{if(!popup.closed)popup.close();}catch(_){}return session;}
    if(session.status==='error')throw new Error(session.error||'Google-Anmeldung fehlgeschlagen.');
    await new Promise(resolve=>setTimeout(resolve,700));
  }
  throw new Error('Google-Anmeldung hat zu lange gedauert. Bitte erneut versuchen.');
}

async function probeProvider(){busy=true;render();try{probe=await post('/v1/providers/probe',{provider:form.provider});if(probe.models?.length&&!form.model)form.model=probe.models[0];if(!probe.available)showNotice(probe.detail,'error')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function finishOnboarding(){saveVisible();busy=true;render();try{await post('/v1/onboarding/complete',{profile:{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType,autonomy_mode:form.autonomy,language:form.language,tone:form.tone,response_length:'medium',use_humor:false,salutation_style:'adaptive',email_signature:form.emailSignature},provider:form.provider,model:form.model||'default'});installed=true;await loadDashboard(true);showNotice('MAIL-AGENT ist bereit.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}

function navItem(view,label,ico,badge='') { return `<button class="nav-item ${activeView===view?'active':''}" data-view="${view}">${icon(ico,19)}<span>${label}</span>${badge?`<b>${badge}</b>`:''}</button>`; }
function dashboardLayout(content) {
  const agentName=form.agentName||identity?.agent_name||'MAIL-AGENT';
  return `<main class="dashboard"><aside class="sidebar">${brand(true)}<nav>${navItem('overview','Übersicht','home')}${navItem('inbox','Inbox','inbox',dashboard.messages.length||'')}${navItem('approvals','Freigaben','shield',dashboard.approvals.length||'')}${navItem('drafts','Entwürfe','draft',dashboard.drafts.length||'')}${navItem('settings','Einstellungen','settings')}</nav><div class="sidebar-bottom"><div class="agent-mini"><span class="avatar">${esc(agentName.slice(0,1).toUpperCase())}</span><span><b>${esc(agentName)}</b><small><i></i> Aktiv</small></span></div></div></aside><section class="workspace"><header class="topbar"><div><span class="workspace-kicker">MAIL-AGENT</span><h1>${viewTitle()}</h1></div><div class="top-actions"><button class="btn secondary compact" id="sync-now">${icon('sync',16)}Synchronisieren</button><span class="status-pill"><i></i> Gateway online</span></div></header><div class="workspace-body">${content}</div></section></main>`;
}
function viewTitle(){return ({overview:'Übersicht',inbox:'Inbox',approvals:'Freigaben',drafts:'Entwürfe',settings:'Einstellungen'})[activeView]||'Übersicht';}
function metric(label,value,sub,ico){return `<div class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon(ico,18)}</span></div><strong>${esc(value)}</strong><small>${esc(sub)}</small></div>`;}

function emptyState(ico, title, text) { return `<div class="empty-state large">${icon(ico,30)}<b>${esc(title)}</b><span>${esc(text)}</span></div>`; }
function renderDashboard(){
  const mailbox=dashboard.mailboxes[0]; const sync=mailbox?.sync||{};
  let content='';
  if(activeView==='overview') content=`<section class="hero-card"><div><span class="hero-kicker">DEIN AGENT IST BEREIT</span><h2>${esc(form.agentName||'MAIL-AGENT')} hält dein Postfach im Blick.</h2><p>Neue Nachrichten werden lokal synchronisiert, analysiert und nur innerhalb deiner Regeln bearbeitet.</p><div class="hero-actions"><button class="btn primary" data-view="inbox">Inbox öffnen${icon('chevron',16)}</button><button class="btn secondary" data-view="approvals">Freigaben prüfen</button></div></div><div class="hero-orb">${icon('spark',38)}</div></section><div class="stats-grid">${metric('Postfach',mailbox?.email_address||'Nicht verbunden',mailbox?.credential_available?'Vault geschützt':'Credential fehlt','mail')}${metric('Inbox',dashboard.messages.length,'lokal geladene Nachrichten','inbox')}${metric('Freigaben',dashboard.approvals.length,'warten auf deine Entscheidung','shield')}${metric('Entwürfe',dashboard.drafts.length,'vom Agenten vorbereitet','draft')}</div><section class="panel"><div class="panel-head"><div><span>LETZTE NACHRICHTEN</span><h3>Inbox</h3></div><button class="link-btn" data-view="inbox">Alle anzeigen →</button></div>${dashboard.messages.length?dashboard.messages.slice(0,5).map(mailRow).join(''):'<div class="empty-state">Noch keine Nachrichten synchronisiert.</div>'}</section>`;
  if(activeView==='inbox') content=`<section class="panel full"><div class="panel-head"><div><span>LOKAL SYNCHRONISIERT</span><h3>${esc(mailbox?.email_address||'Inbox')}</h3></div><span class="muted">${sync.last_synced_at?`Zuletzt ${esc(new Date(sync.last_synced_at).toLocaleString())}`:'Noch kein Sync'}</span></div>${dashboard.messages.length?dashboard.messages.map(mailRow).join(''):emptyState('inbox','Deine Inbox ist noch leer','Starte die erste Synchronisierung oben rechts.')}</section>`;
  if(activeView==='approvals') content=`<section class="panel full"><div class="panel-head"><div><span>HUMAN-IN-THE-LOOP</span><h3>Freigabe-Queue</h3></div><span class="badge">${dashboard.approvals.length} offen</span></div>${dashboard.approvals.length?dashboard.approvals.map(approvalCard).join(''):emptyState('shield','Alles erledigt','Es gibt aktuell keine offenen Aktionen.')}</section>`;
  if(activeView==='drafts') content=`<section class="panel full"><div class="panel-head"><div><span>VORBEREITET VON ${esc((form.agentName||'Agent').toUpperCase())}</span><h3>Entwürfe</h3></div><span class="badge">${dashboard.drafts.length}</span></div>${dashboard.drafts.length?dashboard.drafts.map(draftCard).join(''):emptyState('draft','Noch keine Entwürfe','Sobald dein Agent Antworten vorbereitet, erscheinen sie hier.')}</section>`;
  if(activeView==='settings') content=`<div class="settings-grid"><section class="panel"><div class="panel-head"><div><span>AGENT</span><h3>Persönlichkeit</h3></div></div><div class="setting-row"><span>Name</span><b>${esc(form.agentName)}</b></div><div class="setting-row"><span>Einsatz</span><b>${esc(form.usageType)}</b></div><div class="setting-row"><span>Ton</span><b>${esc(form.tone)}</b></div><div class="setting-row"><span>Autonomie</span><b>${esc(form.autonomy)}</b></div></section><section class="panel"><div class="panel-head"><div><span>SICHERHEIT</span><h3>Lokale Vertrauensbasis</h3></div></div><div class="security-block">${icon('lock',22)}<div><b>Credential Vault aktiv</b><p>Mailbox-Secrets und Agent-Schlüssel bleiben lokal geschützt.</p></div></div><div class="security-block">${icon('shield',22)}<div><b>Freigaben erzwungen</b><p>Senden, Löschen und Weiterleiten können nicht vom Modell selbst freigegeben werden.</p></div></div></section></div>`;
  app.innerHTML=dashboardLayout(content); if(activeView==='settings')renderUpdatePanel(); bindDashboard();
}
function mailRow(item){const preview=String(item.body_text||'').replace(/\s+/g,' ').slice(0,120);return `<article class="mail-row"><span class="mail-avatar">${esc((item.sender||'?').slice(0,1).toUpperCase())}</span><div class="mail-main"><div class="mail-line"><b>${esc(item.sender||'Unbekannt')}</b><span>${esc(item.sent_at?new Date(item.sent_at).toLocaleDateString():'')}</span></div><h4>${esc(item.subject||'(ohne Betreff)')}</h4><p>${esc(preview)}${(item.body_text||'').length>120?'…':''}</p></div><span class="row-arrow">${icon('chevron',17)}</span></article>`;}
function approvalCard(item){const p=item.proposal||{};return `<article class="approval"><span class="risk-icon">${icon('shield',19)}</span><div class="approval-copy"><div class="mail-line"><b>${esc(item.action)}</b><span>Risiko: ${esc(item.policy?.risk||'')}</span></div><h4>${esc(p.subject||p.recipient||'Mail-Aktion')}</h4><p>${esc(p.reason||item.policy?.reason||'')}</p></div><div class="approval-actions"><button class="btn secondary compact" data-reject="${esc(item.approval_id)}">${icon('x',15)} Ablehnen</button><button class="btn primary compact" data-approve="${esc(item.approval_id)}">${icon('check',15)} Freigeben</button></div></article>`;}
function draftCard(item){return `<article class="draft-card"><div class="draft-head"><span>${icon('draft',18)}</span><div><b>${esc(item.subject||'(ohne Betreff)')}</b><small>An ${esc(item.recipient||'offen')}</small></div><span class="badge soft">${esc(item.status)}</span></div><p>${esc(String(item.body||'').slice(0,240))}${(item.body||'').length>240?'…':''}</p></article>`;}

function renderUpdatePanel(){
  const grid=document.querySelector('.settings-grid');
  if(!grid)return;
  const current=updateStatus?.current_version||'0.3.0';
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

function bindDashboard(){document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>{activeView=el.dataset.view;render();});document.getElementById('sync-now')?.addEventListener('click',syncNow);document.querySelectorAll('[data-approve]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.approve,'approve'));document.querySelectorAll('[data-reject]').forEach(el=>el.onclick=()=>decideApproval(el.dataset.reject,'reject'));}
async function loadDashboard(silent=false){if(!silent)busy=true;try{const mb=await get('/v1/mailboxes');dashboard.mailboxes=mb.mailboxes||[];dashboard.approvals=(await get('/v1/approvals?status=pending&limit=50')).approvals||[];dashboard.drafts=(await get('/v1/drafts?limit=50')).drafts||[];const active=dashboard.mailboxes[0];dashboard.messages=active?(await get(`/v1/mailboxes/${encodeURIComponent(active.mailbox_id)}/messages?limit=50`)).messages||[]:[];}catch(e){showNotice(e.message,'error')}finally{busy=false;}}
async function syncNow(){const mb=dashboard.mailboxes[0];if(!mb)return;busy=true;render();try{await post('/v1/sync/run',{mailbox_id:mb.mailbox_id,limit:100});await loadDashboard(true);showNotice('Postfach ist aktuell.')}catch(e){showNotice(e.message,'error')}finally{busy=false;render()}}
async function decideApproval(id,decision){try{await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`,{actor:'local-user'});await loadDashboard(true);showNotice(decision==='approve'?'Aktion freigegeben.':'Aktion abgelehnt.');render();}catch(e){showNotice(e.message,'error')}}
function render(){installed?renderDashboard():renderSetup();}
async function boot(){try{const [status,oauth]=await Promise.all([get('/v1/onboarding/status'),get('/v1/oauth/providers').catch(()=>({google:{configured:false}}))]);oauthProviders=oauth||oauthProviders;if(status.identity){identity=status.identity;form.ownerId=identity.owner_id||'';form.agentName=identity.agent_name||'Nova';form.usageType=identity.usage_type||'private';}const mb=status.mailboxes?.[0]||status.mailbox;if(mb){mailboxConnected=true;mailboxId=mb.mailbox_id;mailboxConnector=mb.connector||'imap';form.emailAddress=mb.email_address||'';form.mailboxUsername=mb.username||'';form.imapHost=mb.imap_host||'';form.imapPort=mb.imap_port||993;form.smtpHost=mb.smtp_host||'';form.smtpPort=mb.smtp_port||465;}if(status.configuration){const c=status.configuration,p=c.profile||{};form.provider=c.provider||form.provider;form.model=c.model||form.model;form.autonomy=p.autonomy_mode||form.autonomy;form.language=p.language||form.language;form.tone=p.tone||form.tone;form.emailSignature=p.email_signature||'';}installed=!!status.completed;if(installed)await loadDashboard(true);}catch(e){showNotice(`Gateway nicht bereit: ${e.message}`,'error')}render();}
boot();
