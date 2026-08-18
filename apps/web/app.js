const gateway = location.origin;
const steps = ['Identität', 'Einsatz', 'Postfach', 'KI-Modell', 'Persönlichkeit', 'Autonomie', 'Aktivieren'];
let step = 0;
let identity = null;
let probe = null;
let busy = false;
let dashboardMode = false;
let dashboard = { mailboxes: [], approvals: [], messages: [], drafts: [] };
const form = {
  ownerId: '', agentName: 'Nova', usageType: 'private', provider: 'ollama', model: '',
  autonomy: 'assistant', tone: 'friendly', language: 'de', emailSignature: '',
  emailAddress: '', mailboxUsername: '', mailboxPassword: '', imapHost: '', imapPort: 993, smtpHost: '', smtpPort: 465
};
let mailboxConnected = false;
let mailboxId = null;

const app = document.querySelector('#app');
const notice = document.querySelector('#notice');

function esc(value = '') {
  return String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}
function showNotice(text, kind='') {
  notice.textContent = text;
  notice.className = `notice ${kind}`;
}
function clearNotice() { notice.textContent = ''; notice.className = 'notice hidden'; }
async function request(path, options = {}) {
  const response = await fetch(`${gateway}${path}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
async function get(path) { return request(path); }
async function post(path, body) {
  return request(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
}
function setStep(next) { step = Math.max(0, Math.min(steps.length - 1, next)); clearNotice(); render(); }
function updateHeader() {
  const counter = document.querySelector('#step-counter');
  const name = document.querySelector('#step-name');
  const bar = document.querySelector('#progress-bar');
  if (dashboardMode) {
    counter.textContent = 'MAIL-AGENT v0.2';
    name.textContent = 'Control Center';
    bar.style.width = '100%';
    return;
  }
  counter.textContent = `Setup ${step + 1} / ${steps.length}`;
  name.textContent = steps[step];
  bar.style.width = `${((step + 1) / steps.length) * 100}%`;
}
function stepShell(icon, title, subtitle, body) {
  return `<div class="step"><div class="step-icon">${icon}</div><h2>${title}</h2><p class="subtitle">${subtitle}</p><div class="form">${body}</div></div>`;
}
function info(text, tone='') { return `<div class="info ${tone}"><span>◇</span><span>${text}</span></div>`; }
function nav(back, next, disabled=false) { return `<div class="nav"><button class="ghost" data-go="${back}">← Zurück</button><button class="primary" data-go="${next}" ${disabled?'disabled':''}>Weiter →</button></div>`; }
function choice(value, title, text, selected, group, icon='') {
  return `<button class="choice ${selected?'active':''}" data-choice-group="${group}" data-choice="${value}">${icon ? `<span class="choice-icon">${icon}</span>`:''}<span><strong>${title}</strong><small>${text}</small></span>${selected?'<i class="check">✓</i>':''}</button>`;
}
function summary(label, value) { return `<div class="summary-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`; }

function render() {
  updateHeader();
  if (dashboardMode) {
    renderDashboard();
    return;
  }
  if (step === 0) {
    app.innerHTML = stepShell('⌁', 'Gib deinem Agenten eine Identität', 'Jede Installation erhält eine eindeutige kryptografische Signatur und wird einem Owner zugeordnet.', `
      <label>Owner-ID oder Accountname<input id="owner" value="${esc(form.ownerId)}" placeholder="z. B. steffen"></label>
      <label>Name des Agenten<input id="agent-name" value="${esc(form.agentName)}"></label>
      ${info('Beim Fortfahren erzeugt MAIL-AGENT lokal ein Ed25519-Schlüsselpaar. Nur der öffentliche Schlüssel wird registriert.')}
      <button class="primary" id="identity-next" ${!form.ownerId || !form.agentName ? 'disabled':''}>Weiter →</button>
    `);
  } else if (step === 1) {
    app.innerHTML = stepShell('◎', 'Wofür arbeitet dein Agent?', 'Der Einsatzbereich bestimmt Sicherheits-Defaults und Tonalität.', `
      <div class="cards two">
        ${choice('private','Privat','Persönliche Kommunikation und Alltag.',form.usageType==='private','usage','⌂')}
        ${choice('work','Arbeit','Konservativere Regeln für berufliche Mail.',form.usageType==='work','usage','▣')}
        ${choice('business','Business','Geschäftliche Konten mit strengen Freigaben.',form.usageType==='business','usage','◇')}
        ${choice('custom','Individuell','Eigene Regeln detailliert konfigurieren.',form.usageType==='custom','usage','✦')}
      </div>
      ${identity ? info(`Agent <code>${esc(identity.agent_id.slice(0,18))}…</code> registriert · Fingerprint <code>${esc(identity.fingerprint.slice(0,14))}…</code>`, 'good') : ''}
      <div class="nav"><button class="ghost" data-go="0">← Zurück</button><button class="primary" id="create-identity" ${busy?'disabled':''}>${busy?'Registriere…':'Identität registrieren →'}</button></div>
    `);
  } else if (step === 2) {
    app.innerHTML = stepShell('✉', 'Verbinde dein erstes Postfach', 'MAIL-AGENT prüft IMAP und SMTP und legt das Passwort danach verschlüsselt im lokalen Credential Vault ab.', `
      <div class="field-grid">
        <label>E-Mail-Adresse<input id="email-address" value="${esc(form.emailAddress)}" placeholder="name@example.com"></label>
        <label>Benutzername<input id="mailbox-username" value="${esc(form.mailboxUsername)}" placeholder="meist die E-Mail-Adresse"></label>
        <label>IMAP-Server<input id="imap-host" value="${esc(form.imapHost)}" placeholder="imap.example.com"></label>
        <label>IMAP-Port<input id="imap-port" type="number" value="${form.imapPort}"></label>
        <label>SMTP-Server<input id="smtp-host" value="${esc(form.smtpHost)}" placeholder="smtp.example.com"></label>
        <label>SMTP-Port<input id="smtp-port" type="number" value="${form.smtpPort}"></label>
      </div>
      <label>Passwort / App-Passwort<input id="mailbox-password" type="password" value="${esc(form.mailboxPassword)}" autocomplete="new-password"></label>
      ${info('v0.2: Secrets werden mit AES-256-GCM verschlüsselt. Weder state.json noch die lokale Mail-Datenbank enthalten das Passwort.')}
      <button class="secondary" id="probe-mailbox" ${busy?'disabled':''}>${busy?'Prüfe…':'IMAP + SMTP testen & sicher speichern'}</button>
      ${mailboxConnected ? info(`Postfach ${esc(form.emailAddress)} verbunden · Credential Vault aktiv.`, 'good') : ''}
      ${nav(1,3,!mailboxConnected)}
    `);
  } else if (step === 3) {
    const models = probe?.models?.length ? `<label>Modell<select id="model-select">${probe.models.map(m=>`<option ${m===form.model?'selected':''}>${esc(m)}</option>`).join('')}</select></label>` : '';
    app.innerHTML = stepShell('◈', 'Wähle das Gehirn', 'Provider sind austauschbar. Mail-Zugang und Aktionsrechte bleiben immer beim Gateway.', `
      <div class="cards two">
        ${choice('ollama','Ollama','Lokale Modelle. Mail-Inhalte bleiben auf deinem Gerät.',form.provider==='ollama','provider','◉')}
        ${choice('codex','ChatGPT / Codex','Verwendet den lokal angemeldeten Codex-Client statt eines eingetragenen API-Keys.',form.provider==='codex','provider','☁')}
      </div>
      <button class="secondary" id="probe-provider" ${busy?'disabled':''}>${busy?'Prüfe…':'Verbindung prüfen'}</button>
      ${probe ? info(esc(probe.detail), probe.available?'good':'warn') : ''}
      ${models}
      ${nav(2,4,!probe?.available)}
    `);
  } else if (step === 4) {
    app.innerHTML = stepShell('✦', 'Wie soll dein Agent schreiben?', 'Die Persönlichkeit wird pro Agent gespeichert und später pro Mailkonto überschreibbar.', `
      <div class="field-grid">
        <label>Sprache<select id="language"><option value="de" ${form.language==='de'?'selected':''}>Deutsch</option><option value="en" ${form.language==='en'?'selected':''}>English</option></select></label>
        <label>Grundton<select id="tone"><option value="friendly" ${form.tone==='friendly'?'selected':''}>Freundlich</option><option value="professional" ${form.tone==='professional'?'selected':''}>Professionell</option><option value="direct" ${form.tone==='direct'?'selected':''}>Direkt</option><option value="warm" ${form.tone==='warm'?'selected':''}>Warm</option></select></label>
      </div>
      <label>E-Mail-Signatur<textarea id="email-signature" rows="5" placeholder="Viele Grüße\nSteffen">${esc(form.emailSignature)}</textarea></label>
      ${nav(3,5)}
    `);
  } else if (step === 5) {
    app.innerHTML = stepShell('◇', 'Wie selbstständig darf er sein?', 'Hohe Auswirkungen bleiben in v0.2 immer freigabepflichtig – selbst im autonomen Modus.', `
      <div class="stack">
        ${choice('observer','Observer','Nur lesen, analysieren und priorisieren.',form.autonomy==='observer','autonomy')}
        ${choice('assistant','Assistant','Zusätzlich Antwortentwürfe erstellen.',form.autonomy==='assistant','autonomy')}
        ${choice('copilot','Copilot','Darf sortieren und archivieren; Senden braucht Freigabe.',form.autonomy==='copilot','autonomy')}
        ${choice('autonomous','Autonomous','Automatisiert erlaubte Aktionen nach festen Regeln.',form.autonomy==='autonomous','autonomy')}
      </div>
      ${nav(4,6)}
    `);
  } else {
    app.innerHTML = stepShell('✓', 'Bereit für MAIL-AGENT', 'Prüfe die Kernkonfiguration. Danach übernimmt der lokale Sync-Worker dein Postfach.', `
      <div class="summary">
        ${summary('Agent',form.agentName)}${summary('Einsatz',form.usageType)}${summary('Modell',`${form.provider} / ${form.model || 'default'}`)}${summary('Autonomie',form.autonomy)}${summary('Postfach',form.emailAddress || 'Fehlt')}${summary('Credential Vault',mailboxConnected?'Aktiv':'Fehlt')}${summary('E-Mail-Signatur',form.emailSignature?'Konfiguriert':'Noch leer')}${summary('Agent-Identität',identity?'Registriert':'Fehlt')}
      </div>
      ${info('Senden, Weiterleiten und Löschen landen in der Approval Queue und werden nicht durch das Modell selbst freigegeben.')}
      <div class="nav"><button class="ghost" data-go="5">← Zurück</button><button class="primary" id="finish" ${busy||!identity?'disabled':''}>${busy?'Aktiviere…':'Agent aktivieren ✓'}</button></div>
    `);
  }
  bind();
}

function renderDashboard() {
  const mailbox = dashboard.mailboxes[0];
  const sync = mailbox?.sync || {};
  const approvals = dashboard.approvals || [];
  const messages = dashboard.messages || [];
  const drafts = dashboard.drafts || [];
  app.innerHTML = stepShell('◉', 'Control Center', 'Lokaler Mail-Sync, Inbox und menschliche Freigaben an einem Ort.', `
    <div class="metric-grid">
      <div class="metric"><span>Postfach</span><strong>${mailbox ? esc(mailbox.email_address) : 'Nicht verbunden'}</strong><small>${mailbox?.credential_available ? 'Vault ✓' : 'Credential fehlt'}</small></div>
      <div class="metric"><span>Letzter UID</span><strong>${esc(sync.last_uid ?? 0)}</strong><small>${sync.last_synced_at ? esc(new Date(sync.last_synced_at).toLocaleString()) : 'Noch kein Sync'}</small></div>
      <div class="metric"><span>Freigaben</span><strong>${approvals.length}</strong><small>offen</small></div>
      <div class="metric"><span>Entwürfe</span><strong>${drafts.length}</strong><small>lokal gespeichert</small></div>
    </div>
    ${sync.last_error ? info(`Letzter Sync-Fehler: ${esc(sync.last_error)}`, 'warn') : info('Der Sync liest per IMAP UID + BODY.PEEK[] und verändert den Gelesen-Status nicht.', 'good')}
    <div class="toolbar"><button class="primary" id="sync-now" ${busy||!mailbox?'disabled':''}>${busy?'Synchronisiere…':'Jetzt synchronisieren'}</button><button class="secondary" id="refresh-dashboard">Aktualisieren</button></div>
    <section class="dashboard-section"><div class="section-head"><h3>Approval Queue</h3><span>${approvals.length} offen</span></div>
      ${approvals.length ? approvals.map(approvalCard).join('') : '<div class="empty">Keine offenen Freigaben.</div>'}
    </section>
    <section class="dashboard-section"><div class="section-head"><h3>Entwürfe</h3><span>${drafts.length} gespeichert</span></div>
      ${drafts.length ? drafts.slice(0,5).map(draftCard).join('') : '<div class="empty">Noch keine Agent-Entwürfe.</div>'}
    </section>
    <section class="dashboard-section"><div class="section-head"><h3>Lokale Inbox</h3><span>${messages.length} angezeigt</span></div>
      ${messages.length ? messages.map(messageCard).join('') : '<div class="empty">Noch keine lokal synchronisierten Nachrichten.</div>'}
    </section>
  `);
  bindDashboard();
}

function approvalCard(item) {
  const p = item.proposal || {};
  return `<div class="approval-card"><div><strong>${esc(item.action)}</strong><small>${esc(p.subject || p.recipient || item.message_id || 'Mail-Aktion')}</small><p>${esc(p.reason || item.policy?.reason || '')}</p></div><div class="approval-actions"><button class="secondary" data-reject="${esc(item.approval_id)}">Ablehnen</button><button class="primary" data-approve="${esc(item.approval_id)}">Freigeben</button></div></div>`;
}
function draftCard(item) {
  const preview = String(item.body || '').replace(/\s+/g, ' ').slice(0, 180);
  return `<article class="mail-card"><div class="mail-meta"><strong>${esc(item.recipient || 'Empfänger offen')}</strong><span>${esc(item.status)}</span></div><h4>${esc(item.subject || '(ohne Betreff)')}</h4><p>${esc(preview)}${(item.body||'').length>180?'…':''}</p></article>`;
}
function messageCard(item) {
  const preview = String(item.body_text || '').replace(/\s+/g, ' ').slice(0, 180);
  return `<article class="mail-card"><div class="mail-meta"><strong>${esc(item.sender || 'Unbekannt')}</strong><span>UID ${esc(item.uid)}</span></div><h4>${esc(item.subject || '(ohne Betreff)')}</h4><p>${esc(preview)}${(item.body_text||'').length>180?'…':''}</p></article>`;
}

function bind() {
  document.querySelectorAll('[data-go]').forEach(el => el.addEventListener('click', () => {
    persistVisibleFields(); setStep(Number(el.dataset.go));
  }));
  document.querySelectorAll('[data-choice-group]').forEach(el => el.addEventListener('click', () => {
    const group = el.dataset.choiceGroup, value = el.dataset.choice;
    if (group === 'usage') form.usageType = value;
    if (group === 'provider') { form.provider = value; form.model = value === 'codex' ? 'default' : ''; probe = null; }
    if (group === 'autonomy') form.autonomy = value;
    render();
  }));
  document.querySelector('#owner')?.addEventListener('input', e => { form.ownerId = e.target.value; const b=document.querySelector('#identity-next'); if(b)b.disabled = !form.ownerId || !form.agentName; });
  document.querySelector('#agent-name')?.addEventListener('input', e => { form.agentName = e.target.value; const b=document.querySelector('#identity-next'); if(b)b.disabled = !form.ownerId || !form.agentName; });
  document.querySelector('#identity-next')?.addEventListener('click', () => { persistVisibleFields(); setStep(1); });
  document.querySelector('#model-select')?.addEventListener('change', e => form.model = e.target.value);
  document.querySelector('#create-identity')?.addEventListener('click', createIdentity);
  document.querySelector('#probe-mailbox')?.addEventListener('click', probeMailbox);
  document.querySelector('#probe-provider')?.addEventListener('click', probeProvider);
  document.querySelector('#finish')?.addEventListener('click', finish);
}
function bindDashboard() {
  document.querySelector('#refresh-dashboard')?.addEventListener('click', loadDashboard);
  document.querySelector('#sync-now')?.addEventListener('click', syncNow);
  document.querySelectorAll('[data-approve]').forEach(el => el.addEventListener('click', () => decideApproval(el.dataset.approve, 'approve')));
  document.querySelectorAll('[data-reject]').forEach(el => el.addEventListener('click', () => decideApproval(el.dataset.reject, 'reject')));
}
function persistVisibleFields() {
  const language = document.querySelector('#language'); if (language) form.language = language.value;
  const tone = document.querySelector('#tone'); if (tone) form.tone = tone.value;
  const signature = document.querySelector('#email-signature'); if (signature) form.emailSignature = signature.value;
  const model = document.querySelector('#model-select'); if (model) form.model = model.value;
  const fields = [['#email-address','emailAddress'],['#mailbox-username','mailboxUsername'],['#mailbox-password','mailboxPassword'],['#imap-host','imapHost'],['#smtp-host','smtpHost']];
  fields.forEach(([selector,key]) => { const el=document.querySelector(selector); if(el) form[key]=el.value; });
  const imapPort=document.querySelector('#imap-port'); if(imapPort) form.imapPort=Number(imapPort.value)||993;
  const smtpPort=document.querySelector('#smtp-port'); if(smtpPort) form.smtpPort=Number(smtpPort.value)||465;
}
async function createIdentity() {
  persistVisibleFields(); busy = true; clearNotice(); render();
  try {
    identity = await post('/v1/onboarding/identity',{owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType});
    setStep(2);
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function probeMailbox() {
  persistVisibleFields(); busy = true; mailboxConnected = false; clearNotice(); render();
  try {
    const result = await post('/v1/mailboxes/probe',{email_address:form.emailAddress,username:form.mailboxUsername,password:form.mailboxPassword,imap_host:form.imapHost,imap_port:form.imapPort,smtp_host:form.smtpHost,smtp_port:form.smtpPort});
    mailboxConnected = true;
    mailboxId = result.mailbox_id;
    form.mailboxPassword = '';
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function probeProvider() {
  busy = true; clearNotice(); probe = null; render();
  try {
    probe = await post('/v1/providers/probe',{provider:form.provider});
    if (probe.models?.length && !form.model) form.model = probe.models[0];
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function finish() {
  persistVisibleFields(); busy = true; clearNotice(); render();
  try {
    await post('/v1/onboarding/complete', { profile:{ owner_id:form.ownerId,agent_name:form.agentName,usage_type:form.usageType,autonomy_mode:form.autonomy,language:form.language,tone:form.tone,response_length:'medium',use_humor:false,salutation_style:'adaptive',email_signature:form.emailSignature }, provider:form.provider, model:form.model||'default' });
    dashboardMode = true;
    await loadDashboard(true);
    showNotice('MAIL-AGENT v0.2 ist aktiviert.','success');
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function loadDashboard(silent=false) {
  if (!silent) { busy = true; clearNotice(); render(); }
  try {
    const mailboxData = await get('/v1/mailboxes');
    const approvalData = await get('/v1/approvals?status=pending&limit=50');
    dashboard.mailboxes = mailboxData.mailboxes || [];
    dashboard.approvals = approvalData.approvals || [];
    dashboard.drafts = (await get('/v1/drafts?limit=50')).drafts || [];
    const active = dashboard.mailboxes[0];
    dashboard.messages = active ? (await get(`/v1/mailboxes/${encodeURIComponent(active.mailbox_id)}/messages?limit=20`)).messages || [] : [];
  } catch (err) {
    showNotice(err.message,'error');
  } finally {
    busy = false;
    render();
  }
}
async function syncNow() {
  busy = true; clearNotice(); render();
  try {
    const active = dashboard.mailboxes[0];
    await post('/v1/sync/run', {mailbox_id: active?.mailbox_id || mailboxId, limit: 100});
    await loadDashboard(true);
    showNotice('Postfach erfolgreich synchronisiert.','success');
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function decideApproval(id, decision) {
  busy = true; clearNotice(); render();
  try {
    await post(`/v1/approvals/${encodeURIComponent(id)}/${decision}`, {actor:'local-user'});
    await loadDashboard(true);
    showNotice(decision === 'approve' ? 'Aktion freigegeben.' : 'Aktion abgelehnt.','success');
  } catch (err) { showNotice(err.message,'error'); }
  finally { busy = false; render(); }
}
async function boot() {
  try {
    const status = await get('/v1/onboarding/status');
    if (status.identity) {
      identity = status.identity;
      form.ownerId = status.identity.owner_id || '';
      form.agentName = status.identity.agent_name || 'Nova';
      form.usageType = status.identity.usage_type || 'private';
    }
    const mailbox = status.mailboxes?.[0] || status.mailbox;
    if (mailbox) {
      mailboxConnected = true;
      mailboxId = mailbox.mailbox_id;
      form.emailAddress = mailbox.email_address || '';
      form.mailboxUsername = mailbox.username || '';
      form.imapHost = mailbox.imap_host || '';
      form.imapPort = mailbox.imap_port || 993;
      form.smtpHost = mailbox.smtp_host || '';
      form.smtpPort = mailbox.smtp_port || 465;
    }
    if (status.configuration) {
      const cfg = status.configuration;
      const profile = cfg.profile || {};
      form.provider = cfg.provider || form.provider;
      form.model = cfg.model || form.model;
      form.autonomy = profile.autonomy_mode || form.autonomy;
      form.language = profile.language || form.language;
      form.tone = profile.tone || form.tone;
      form.emailSignature = profile.email_signature || '';
    }
    if (status.completed) {
      dashboardMode = true;
      await loadDashboard(true);
    }
  } catch (err) {
    showNotice(`Gateway nicht bereit: ${err.message}`, 'error');
  }
  render();
}
boot();
