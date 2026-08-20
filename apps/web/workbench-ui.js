/* MAIL-AGENT Workbench UI. Presentation layer only; backend and security semantics stay unchanged. */
(() => {
  const wb = {
    selectedMessage: 0,
    selectedApproval: 0,
    selectedDraft: 0,
    selectedAttention: 0,
    attention: [],
    conversations: [],
    patterns: [],
    selectedWaiting: 0,
    conversationLoading: false,
    settingsSection: 'agent',
    attentionLoading: false,
    inboxFilter: 'all',
    attentionFilter: 'all',
    commandOpen: false,
  };

  const fmtTime = value => {
    if (!value) return '—';
    try { return new Date(value).toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'}); } catch (_) { return '—'; }
  };
  const fmtDate = value => {
    if (!value) return '';
    try { return new Date(value).toLocaleDateString('de-DE', {day:'2-digit', month:'2-digit'}); } catch (_) { return ''; }
  };
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const labelPriority = value => ({urgent:'Dringend',high:'Hoch',normal:'Normal',low:'Niedrig'})[String(value||'').toLowerCase()] || 'Normal';
  const tagClass = value => ['urgent','high'].includes(String(value||'').toLowerCase()) ? 'red' : String(value||'').toLowerCase()==='low' ? 'green' : 'warm';
  const bodyText = item => String(item?.body_text || item?.body || item?.agent_summary || '').trim();

  function railButton(view, ico, label, count='') {
    const active = activeView === view || (view === 'settings' && activeView === 'automation');
    return `<button class="wb-rail-button ${active?'active':''}" data-view="${view}" title="${esc(label)}">${icon(ico,18)}${count?`<span class="rail-count">${esc(count)}</span>`:''}</button>`;
  }
  function navLink(view, label, ico, count='', extra='') {
    const active = activeView === view && (!extra || wb.settingsSection === extra);
    return `<button class="wb-nav-link ${active?'active':''}" data-view="${view}" ${extra?`data-settings-section="${extra}"`:''}>${icon(ico,16)}<span>${esc(label)}</span>${count?`<b>${esc(count)}</b>`:''}</button>`;
  }

  // Onboarding keeps all real controls, but the composition is calmer and desktop-like.
  setupLayout = function workbenchSetupLayout(content) {
    return `<main class="setup-page"><section class="setup-aside">${brand()}<div class="setup-aside-copy"><span class="kicker">LOKALE E-MAIL-AUTOMATION</span><h1>Einrichten.<br><em>Kontrollieren.</em><br>Arbeiten lassen.</h1><p>Sechs kurze Schritte. Identität, Postfach, Modell und Sicherheitsgrenzen bleiben transparent und lokal nachvollziehbar.</p></div><div class="trust-pill">${icon('shield',18)}<span><b>Sicherheitskern bleibt deterministisch</b><small>Das Modell schlägt vor. MAIL-AGENT entscheidet nach Regeln und Freigaben.</small></span></div></section><section class="setup-main"><div class="setup-top"><span>Einrichtung · ${step+1}/${onboardingSteps.length}</span><b>${onboardingSteps[step]}</b></div>${stepper()}<div class="setup-card">${content}</div><div class="setup-foot">MAIL-AGENT · lokales Gateway · Identität & Vault auf diesem Gerät</div></section></main>`;
  };

  viewTitle = function workbenchTitle() {
    return ({overview:'Briefing',inbox:'Eingang',attention:'Wartet auf dich',waiting:'Wartet auf andere',approvals:'Freigaben',drafts:'Entwürfe',automation:'Automationen',activity:'Journal',shadow:'Testlabor',settings:'Agent & Regeln',system:'System'})[activeView] || 'Briefing';
  };

  dashboardLayout = function workbenchLayout(content) {
    const agentName = form.agentName || identity?.agent_name || 'MAIL-AGENT';
    const behavior = runtimeSettings?.behavior || {};
    const pending = Number(brainStatus?.pending_total || 0);
    const statusText = behavior.enabled === false ? 'Pausiert' : behavior.execution_mode === 'shadow' ? 'Shadow' : 'Aktiv';
    const statusColor = behavior.enabled === false ? '#8d9294' : behavior.execution_mode === 'shadow' ? '#deb367' : '#72c593';
    const attentionCount = wb.attention.length;
    const page = viewTitle();
    return `<main class="wb-shell">
      <aside class="wb-rail">
        <button class="wb-mark" data-view="overview" title="MAIL-AGENT">MA</button>
        ${railButton('overview','home','Briefing')}
        ${railButton('inbox','inbox','Eingang',dashboard.messages.length||'')}
        ${railButton('attention','shield','Wartet auf dich',attentionCount||'')}
        ${railButton('approvals','check','Freigaben',dashboard.approvals.length||'')}
        <div class="wb-rail-spacer"></div>
        ${railButton('settings','settings','Agent & Regeln')}
        ${railButton('system','shield','System')}
      </aside>
      <aside class="wb-context">
        <div class="wb-brand"><div><span class="wb-brand-title">MAIL-AGENT</span><span class="wb-brand-sub">${esc(agentName)} · lokaler Arbeitsbereich</span></div><span class="wb-build">0.15.0</span></div>
        <div class="wb-nav-group"><div class="wb-nav-caption">Arbeit</div>
          ${navLink('overview','Briefing','home')}
          ${navLink('inbox','Eingang','inbox',dashboard.messages.length||'')}
          ${navLink('attention','Wartet auf dich','shield',attentionCount||'')}
          ${navLink('waiting','Wartet auf andere','sync',(wb.conversations||[]).filter(x=>x.status==='awaiting_reply').length||'')}
          ${navLink('approvals','Freigaben','check',dashboard.approvals.length||'')}
          ${navLink('drafts','Entwürfe','draft',dashboard.drafts.length||'')}
        </div>
        <div class="wb-nav-group"><div class="wb-nav-caption">Steuerung</div>
          ${navLink('automation','Automationen','sync')}
          ${navLink('activity','Journal','spark',pending||'')}
          ${navLink('shadow','Testlabor','shield',behavior.execution_mode==='shadow'?'S':'')}
        </div>
        <div class="wb-nav-group"><div class="wb-nav-caption">Konfiguration</div>
          ${navLink('settings','Agent & Regeln','settings')}
          ${navLink('system','System','shield',systemHealth?.summary?.error||'')}
        </div>
        <div class="wb-context-bottom"><div class="wb-agent-state"><div class="wb-agent-state-top"><span>${esc(agentName)}</span><span style="color:${statusColor}">${statusText}</span></div><small>${pending?`${pending} Mail${pending===1?'':'s'} warten auf Verarbeitung.`:'Queue aktuell. '} ${dashboard.mailboxes.length?`${dashboard.mailboxes.length} Postfach${dashboard.mailboxes.length===1?'':'ächer'} verbunden.`:'Kein Postfach verbunden.'}</small></div></div>
      </aside>
      <section class="wb-main">
        <header class="wb-commandbar">
          <div class="wb-page-title"><small>MAIL-AGENT / ${esc(activeView)}</small><strong>${esc(page)}</strong></div>
          <button class="wb-command-search" id="wb-command-search">${icon('spark',14)}<span>Suchen oder Aktion ausführen …</span><kbd class="wb-key">Ctrl K</kbd></button>
          <div class="wb-command-actions"><span class="wb-live"><i></i>${esc(statusText)}</span><button class="wb-action" id="sync-now">${icon('sync',14)}Sync</button><button class="wb-action primary" id="wb-run-agent">Agent ausführen</button></div>
        </header>
        <div class="wb-content">${content}</div>
      </section>
    </main>`;
  };

  function renderBriefing() {
    const messages = dashboard.messages || [];
    const attention = wb.attention.length ? wb.attention : messages.filter(m => m.needs_reply === true || ['urgent','high'].includes(String(m.agent_priority||'').toLowerCase()));
    const first = attention.slice(0,5);
    const traces = brainStatus?.activity || brainStatus?.recent_activity || [];
    const mailbox = dashboard.mailboxes[0];
    const behavior = runtimeSettings?.behavior || {};
    const processed = Math.max(0, Number(brainStatus?.activity_summary?.trace_count || 0));
    return `<div class="wb-briefing">
      <div class="wb-section-head"><div><h2>Was heute zählt.</h2><p>Kein Dashboard zum Anschauen – eine Arbeitsliste zum Entscheiden.</p></div><div class="wb-section-meta"><span>${esc(mailbox?.email_address||'Kein Postfach')}</span><span>·</span><span>${behavior.execution_mode==='shadow'?'Shadow Mode':'Live Mode'}</span></div></div>
      <section class="wb-briefing-top"><div class="wb-briefing-copy"><h2>${attention.length?`${attention.length} Dinge brauchen deine Aufmerksamkeit.`:'Du musst gerade nichts entscheiden.'}</h2><p>MAIL-AGENT bündelt Rückfragen, Freigaben und wichtige Mails. Routinearbeit bleibt im Hintergrund; sensible Aktionen bleiben sichtbar und kontrolliert.</p></div><div class="wb-briefing-score"><small>Lokale Aktivität</small><strong>${processed||messages.length}</strong><span>${processed?'protokollierte Agentenläufe':'lokal synchronisierte Nachrichten'}</span></div></section>
      <div class="wb-kpis"><div class="wb-kpi"><small>Eingang</small><strong>${messages.length}</strong><span>lokal verfügbar</span></div><div class="wb-kpi"><small>Wartet auf dich</small><strong>${attention.length}</strong><span>Rückfrage oder Priorität</span></div><div class="wb-kpi"><small>Freigaben</small><strong>${dashboard.approvals.length}</strong><span>Outbound / High-Risk</span></div><div class="wb-kpi"><small>Wartet auf andere</small><strong>${(wb.conversations||[]).filter(x=>x.status==='awaiting_reply').length}</strong><span>laufende Follow-ups</span></div></div>
      <div class="wb-briefing-grid"><section class="wb-surface"><div class="wb-surface-head"><div><strong>Wartet auf dich</strong><small>Nach Relevanz, nicht nach Eingangszeit</small></div><button class="wb-btn ghost" data-view="attention">Öffnen</button></div>${first.length?first.map((item,i)=>`<div class="wb-focus-row" data-view="attention"><span class="wb-focus-bar ${esc(item.agent_priority||'normal')}"></span><div class="wb-focus-copy"><b>${esc(item.subject||'(ohne Betreff)')}</b><p>${esc(item.agent_summary||item.sender||'')}</p></div><div class="wb-focus-meta"><span class="wb-tag ${tagClass(item.agent_priority)}">${esc(labelPriority(item.agent_priority))}</span>${item.needs_reply===true?'<span class="wb-tag">Antwort</span>':''}</div></div>`).join(''):'<div class="wb-empty"><div><b>Keine Rückfragen</b>Der Agent kann weiterarbeiten.</div></div>'}</section>
      <div class="wb-stack"><section class="wb-surface"><div class="wb-surface-head"><div><strong>Systemlage</strong><small>Nur Zustände, die für Arbeit relevant sind</small></div><span class="wb-tag green">bereit</span></div><div class="wb-status-table"><div class="wb-status-row"><span>Mailbox</span><strong>${dashboard.mailboxes.length?'verbunden':'fehlt'}</strong></div><div class="wb-status-row"><span>Ausführungsmodus</span><strong>${behavior.execution_mode==='shadow'?'Shadow':'Live'}</strong></div><div class="wb-status-row"><span>LLM</span><strong>${esc(runtimeSettings?.provider||form.provider||'—')} · ${esc(runtimeSettings?.model||form.model||'default')}</strong></div><div class="wb-status-row"><span>Agent-ID</span><strong>${identity||runtimeSettings?.identity?'signiert':'—'}</strong></div></div></section>
      <section class="wb-surface"><div class="wb-surface-head"><div><strong>Letzte Aktivität</strong><small>Lesbar statt technisch</small></div><button class="wb-btn ghost" data-view="activity">Journal</button></div>${traces.length?traces.slice(0,5).map(t=>`<div class="wb-activity-row"><time>${fmtTime(t.started_at||t.at)}</time><span>${esc(t.subject||t.event||t.reason||'Agentenaktivität')}</span></div>`).join(''):'<div class="wb-empty"><div><b>Noch keine Aktivität</b>Neue Läufe erscheinen hier.</div></div>'}</section></div></div>
    </div>`;
  }

  function renderInbox() {
    const allItems = dashboard.messages || [];
    const items = allItems.filter(item => wb.inboxFilter==='important' ? (item.needs_reply===true || ['urgent','high'].includes(String(item.agent_priority||'').toLowerCase())) : wb.inboxFilter==='unread' ? (item.is_read===false || item.read===false) : true);
    wb.selectedMessage = Math.max(0, Math.min(wb.selectedMessage, Math.max(0, items.length-1)));
    const selected = items[wb.selectedMessage];
    return `<div class="wb-split"><section class="wb-list-pane"><div class="wb-pane-head"><div><strong>Eingang</strong><span>${items.length} von ${allItems.length} angezeigt</span></div><div class="wb-filter-row"><button class="wb-filter ${wb.inboxFilter==='all'?'active':''}" data-inbox-filter="all">Alle</button><button class="wb-filter ${wb.inboxFilter==='important'?'active':''}" data-inbox-filter="important">Wichtig</button><button class="wb-filter ${wb.inboxFilter==='unread'?'active':''}" data-inbox-filter="unread">Ungelesen</button></div></div><div class="wb-list-scroll">${items.length?items.map((item,i)=>`<button class="wb-list-row ${i===wb.selectedMessage?'active':''}" data-mail-select="${i}"><div class="wb-list-line"><b>${esc(item.sender||'Unbekannt')}</b><time>${fmtDate(item.sent_at)}</time></div><h4>${esc(item.subject||'(ohne Betreff)')}</h4><p>${esc(item.agent_summary||clean(item.body_text).slice(0,160)||'Noch keine Zusammenfassung')}</p><div class="wb-list-line"><span class="wb-tag ${tagClass(item.agent_priority)}">${esc(labelPriority(item.agent_priority))}</span><span>${item.needs_reply===true?'<span class="wb-tag warm">Antwort nötig</span>':''}</span></div></button>`).join(''):'<div class="wb-empty"><div><b>Eingang leer</b>Synchronisiere dein Postfach.</div></div>'}</div></section>${selected?`<section class="wb-detail-pane"><header class="wb-detail-header"><div class="wb-detail-eyebrow"><span>${esc(selected.sender||'Unbekannt')}</span><span>${esc(selected.sent_at?new Date(selected.sent_at).toLocaleString('de-DE'):'')}</span></div><h2>${esc(selected.subject||'(ohne Betreff)')}</h2><p>${esc(selected.recipient||selected.to||'')}</p><div class="wb-risk-strip"><span class="wb-tag ${tagClass(selected.agent_priority)}">${esc(labelPriority(selected.agent_priority))}</span>${selected.agent_category?`<span class="wb-tag">${esc(selected.agent_category)}</span>`:''}${selected.needs_reply===true?'<span class="wb-tag warm">Antwort nötig</span>':''}</div></header><div class="wb-detail-body"><div class="wb-intel-grid"><div class="wb-intel-cell"><small>Priorität</small><strong>${esc(labelPriority(selected.agent_priority))}</strong></div><div class="wb-intel-cell"><small>Kategorie</small><strong>${esc(selected.agent_category||'—')}</strong></div><div class="wb-intel-cell"><small>Agent</small><strong>${selected.needs_reply===true?'Rückmeldung nötig':'Keine Aktion nötig'}</strong></div></div>${selected.agent_summary?`<div class="wb-detail-summary"><small>Zusammenfassung</small><p>${esc(selected.agent_summary)}</p></div>`:''}<div class="wb-message-body">${esc(bodyText(selected)||'Kein lokaler Nachrichtentext verfügbar.')}</div></div><footer class="wb-detail-footer">${selected.needs_reply===true?'<button class="wb-btn" data-view="attention">Zu Rückfragen</button>':''}<button class="wb-btn primary" id="wb-run-agent-context">Agent für Eingang ausführen</button></footer></section>`:'<section class="wb-detail-pane"><div class="wb-empty"><div><b>Keine Nachricht ausgewählt</b>Wähle links eine Mail aus.</div></div></section>'}</div>`;
  }

  async function loadAttention(silent=true) {
    if (wb.attentionLoading) return;
    wb.attentionLoading = true;
    try { const result = await get('/v1/attention?limit=200'); wb.attention = result.attention || []; }
    catch (error) { if (!silent) showNotice(error.message,'error'); }
    finally { wb.attentionLoading = false; }
  }


  async function loadConversationIntelligence(silent=true) {
    if (wb.conversationLoading) return;
    wb.conversationLoading = true;
    try {
      const result = await get('/v1/conversations?limit=300');
      wb.conversations = result.threads || [];
      wb.patterns = result.patterns || [];
    } catch (error) { if (!silent) showNotice(error.message,'error'); }
    finally { wb.conversationLoading = false; }
  }

  function renderAttention() {
    const allItems = wb.attention || [];
    const items = allItems.filter(item => wb.attentionFilter==='urgent' ? ['urgent','high'].includes(String(item.agent_priority||'').toLowerCase()) : true);
    wb.selectedAttention = Math.max(0, Math.min(wb.selectedAttention, Math.max(0,items.length-1)));
    const item = items[wb.selectedAttention];
    const id = item ? String(item.remote_id || item.internet_message_id || item.uid || '') : '';
    return `<div class="wb-split"><section class="wb-list-pane"><div class="wb-pane-head"><div><strong>Wartet auf dich</strong><span>${items.length} offene Entscheidungen</span></div><div class="wb-filter-row"><button class="wb-filter ${wb.attentionFilter==='all'?'active':''}" data-attention-filter="all">Alle</button><button class="wb-filter ${wb.attentionFilter==='urgent'?'active':''}" data-attention-filter="urgent">Dringend</button></div></div><div class="wb-list-scroll">${items.length?items.map((m,i)=>`<button class="wb-list-row ${i===wb.selectedAttention?'active':''}" data-attention-select="${i}"><div class="wb-list-line"><b>${esc(m.sender||'Unbekannt')}</b><span class="wb-tag ${tagClass(m.agent_priority)}">${esc(labelPriority(m.agent_priority))}</span></div><h4>${esc(m.subject||'(ohne Betreff)')}</h4><p>${esc(m.agent_summary||'Der Agent benötigt deine Entscheidung.')}</p></button>`).join(''):'<div class="wb-empty"><div><b>Alles entschieden</b>Aktuell wartet nichts auf dich.</div></div>'}</div></section>${item?`<section class="wb-detail-pane"><header class="wb-detail-header"><div class="wb-detail-eyebrow"><span>${esc(item.sender||'')}</span><span>${item.attention_source==='shadow'?'Shadow-Ergebnis':'Produktiver Lauf'}</span></div><h2>${esc(item.subject||'(ohne Betreff)')}</h2><div class="wb-risk-strip"><span class="wb-tag ${tagClass(item.agent_priority)}">${esc(labelPriority(item.agent_priority))}</span><span class="wb-tag">${esc(item.agent_category||'other')}</span>${item.needs_reply===true?'<span class="wb-tag warm">Antwort / Entscheidung</span>':''}</div></header><div class="wb-detail-body"><div class="wb-detail-summary"><small>Warum braucht der Agent dich?</small><p>${esc(item.agent_summary||'Diese Mail wurde als wichtig oder antwortbedürftig eingestuft.')}</p></div><div class="wb-explain"><div class="wb-explain-block"><small>Erkannter Kontext</small><p>${esc(item.needs_reply===true?'Im Thread wird eine Entscheidung oder Antwort erwartet.':'Hohe Relevanz / Priorität erkannt.')}</p></div><div class="wb-explain-block"><small>Sicherheitsgrenze</small><p>Eine Rückmeldung hier verändert keine Policy. Senden bleibt separat freigabepflichtig.</p></div></div><div style="margin-top:16px"><label class="wb-editor-field"><span>Deine Rückmeldung an den Agenten</span><textarea class="wb-note" data-attention-note="${esc(id)}" placeholder="Kontext, Entscheidung oder gewünschte Richtung …">${esc(item.owner_note||'')}</textarea></label></div></div><footer class="wb-detail-footer"><button class="wb-btn" data-attention-resolve="${esc(id)}" data-mailbox="${esc(item.mailbox_id||'')}">Als erledigt speichern</button></footer></section>`:'<section class="wb-detail-pane"><div class="wb-empty"><div><b>Keine Rückfragen</b>Der Agent hat gerade nichts für dich.</div></div></section>'}</div>`;
  }


  function renderWaiting() {
    const items = (wb.conversations || []).filter(item => item.status === 'awaiting_reply');
    wb.selectedWaiting = Math.max(0, Math.min(wb.selectedWaiting, Math.max(0, items.length-1)));
    const item = items[wb.selectedWaiting];
    const due = value => { if (!value) return 'ohne Frist'; const d=new Date(value); const diff=Math.ceil((d-Date.now())/86400000); return diff<0?`${Math.abs(diff)} Tag${Math.abs(diff)===1?'':'e'} überfällig`:diff===0?'heute fällig':`in ${diff} Tag${diff===1?'':'en'}`; };
    return `<div class="wb-split"><section class="wb-list-pane"><div class="wb-pane-head"><div><strong>Wartet auf andere</strong><span>${items.length} laufende Gespräche</span></div><span class="wb-tag warm">Follow-up Intelligence</span></div><div class="wb-list-scroll">${items.length?items.map((t,i)=>`<button class="wb-list-row ${i===wb.selectedWaiting?'active':''}" data-waiting-select="${i}"><div class="wb-list-line"><b>${esc(t.last_sender||'Kontakt')}</b><span class="wb-tag ${t.due_at&&new Date(t.due_at)<=new Date()?'red':'warm'}">${esc(due(t.due_at))}</span></div><h4>${esc(t.subject||'(ohne Betreff)')}</h4><p>${esc(t.rationale||'Die Gegenseite ist am Zug.')}</p></button>`).join(''):'<div class="wb-empty"><div><b>Auf keine Antwort warten</b>Aktuell ist kein Gespräch offen, bei dem die Gegenseite am Zug ist.</div></div>'}</div></section>${item?`<section class="wb-detail-pane"><header class="wb-detail-header"><div class="wb-detail-eyebrow"><span>${esc(item.last_sender||'')}</span><span>seit ${esc(item.waiting_since?new Date(item.waiting_since).toLocaleDateString('de-DE'):'—')}</span></div><h2>${esc(item.subject||'(ohne Betreff)')}</h2><div class="wb-risk-strip"><span class="wb-tag warm">Warte auf Antwort</span><span class="wb-tag ${item.due_at&&new Date(item.due_at)<=new Date()?'red':''}">${esc(due(item.due_at))}</span>${item.followup_draft_id?'<span class="wb-tag green">Follow-up-Entwurf bereit</span>':''}</div></header><div class="wb-detail-body"><div class="wb-detail-summary"><small>Gesprächszustand</small><p>${esc(item.rationale||'Eine freigegebene Antwort wurde gesendet. MAIL-AGENT wartet auf die Gegenseite.')}</p></div><div class="wb-explain"><div class="wb-explain-block"><small>Automatische Wiedervorlage</small><p>${item.due_at?`MAIL-AGENT prüft diesen Thread ab ${esc(new Date(item.due_at).toLocaleString('de-DE'))}.`:'Für diesen Thread ist keine automatische Frist gesetzt.'}</p></div><div class="wb-explain-block"><small>Coalescing</small><p>${esc(item.coalesced_count||1)} neue Nachricht${Number(item.coalesced_count||1)===1?'':'en'} wurden beim letzten Lauf als ein Gespräch behandelt.</p></div></div>${(item.decision_path||[]).length?`<div class="wb-decision-path"><small>Warum dieser Zustand?</small>${item.decision_path.map(step=>`<div><b>${esc(step.stage)}</b><span>${esc(step.result||'')}</span><p>${esc(step.detail||'')}</p></div>`).join('')}</div>`:''}</div><footer class="wb-detail-footer"><button class="wb-btn" data-snooze-thread="${esc(item.thread_id)}" data-mailbox="${esc(item.mailbox_id)}" data-hours="24">Morgen</button><button class="wb-btn" data-snooze-thread="${esc(item.thread_id)}" data-mailbox="${esc(item.mailbox_id)}" data-hours="72">In 3 Tagen</button>${item.followup_draft_id?'<button class="wb-btn primary" data-view="drafts">Entwurf öffnen</button>':'<span class="wb-tag">Entwurf wird bei Fälligkeit vorbereitet</span>'}</footer></section>`:'<section class="wb-detail-pane"><div class="wb-empty"><div><b>Kein wartendes Gespräch</b></div></div></section>'}</div>`;
  }

  function renderApprovals() {
    const items = dashboard.approvals || [];
    wb.selectedApproval = Math.max(0, Math.min(wb.selectedApproval, Math.max(0,items.length-1)));
    const item = items[wb.selectedApproval];
    const p = item?.proposal || {};
    return `<div class="wb-split"><section class="wb-list-pane"><div class="wb-pane-head"><div><strong>Freigaben</strong><span>${items.length} offene High-Risk-Aktionen</span></div><span class="wb-tag warm">Human in the loop</span></div><div class="wb-list-scroll">${items.length?items.map((a,i)=>`<button class="wb-list-row ${i===wb.selectedApproval?'active':''}" data-approval-select="${i}"><div class="wb-list-line"><b>${esc(a.action||'Aktion')}</b><span class="wb-tag ${a.policy?.risk==='high'?'red':'warm'}">${esc(a.policy?.risk||'prüfen')}</span></div><h4>${esc(a.proposal?.subject||a.proposal?.recipient||'Mail-Aktion')}</h4><p>${esc(a.proposal?.summary||a.proposal?.reason||a.policy?.reason||'')}</p></button>`).join(''):'<div class="wb-empty"><div><b>Keine Freigaben offen</b>Riskante Aktionen warten nicht auf dich.</div></div>'}</div></section>${item?`<section class="wb-detail-pane"><header class="wb-detail-header"><div class="wb-detail-eyebrow"><span>${esc(item.action||'Aktion')}</span><span>Approval ${esc(item.approval_id?.slice(0,8)||'')}</span></div><h2>${esc(p.subject||p.recipient||p.destination_folder||'Freigabe prüfen')}</h2><div class="wb-risk-strip"><span class="wb-tag ${item.policy?.risk==='high'?'red':'warm'}">Risiko ${esc(item.policy?.risk||'—')}</span><span class="wb-tag blue">Policy geprüft</span></div></header><div class="wb-detail-body">${['send_reply','forward'].includes(item.action)?`<div class="wb-compose"><div class="wb-compose-line"><span>An</span><b>${esc(p.recipient||'—')}</b></div><div class="wb-compose-line"><span>Betreff</span><b>${esc(p.subject||'—')}</b></div><div class="wb-compose-body">${esc(p.body||p.content||p.summary||'Kein Entwurfstext im Proposal.')}</div></div>`:`<div class="wb-detail-summary"><small>Vorgeschlagene Aktion</small><p>${esc(p.summary||p.reason||item.policy?.reason||'')}</p></div>`}<div class="wb-explain"><div class="wb-explain-block"><small>Warum vorgeschlagen?</small><p>${esc(p.reason||p.summary||'Der Agent hat diese Aktion aus dem Mail-Kontext vorgeschlagen.')}</p></div><div class="wb-explain-block"><small>Policy-Entscheidung</small><p>${esc(item.policy?.reason||'Die Aktion darf erst nach menschlicher Freigabe ausgeführt werden.')}</p></div></div></div><footer class="wb-detail-footer"><button class="wb-btn danger" data-reject="${esc(item.approval_id)}">Ablehnen</button><button class="wb-btn primary" data-approve="${esc(item.approval_id)}">${['send_reply','forward'].includes(item.action)?'Freigeben & senden':'Freigeben & ausführen'}</button></footer></section>`:'<section class="wb-detail-pane"><div class="wb-empty"><div><b>Queue leer</b>Keine Freigabe ausgewählt.</div></div></section>'}</div>`;
  }

  function renderDrafts() {
    const items = dashboard.drafts || [];
    wb.selectedDraft = Math.max(0, Math.min(wb.selectedDraft, Math.max(0,items.length-1)));
    const item = items[wb.selectedDraft];
    const editing = item && editingDraftId === item.draft_id;
    return `<div class="wb-split"><section class="wb-list-pane"><div class="wb-pane-head"><div><strong>Entwürfe</strong><span>${items.length} lokal vorbereitet</span></div><span class="wb-tag">Agent-ID</span></div><div class="wb-list-scroll">${items.length?items.map((d,i)=>`<button class="wb-list-row ${i===wb.selectedDraft?'active':''}" data-draft-select="${i}"><div class="wb-list-line"><b>${esc(d.recipient||'Kein Empfänger')}</b><span class="wb-tag ${d.status==='sent'?'green':''}">${esc(d.status||'draft')}</span></div><h4>${esc(d.subject||'(ohne Betreff)')}</h4><p>${esc(clean(d.body).slice(0,130))}</p></button>`).join(''):'<div class="wb-empty"><div><b>Keine Entwürfe</b>Der Agent hat noch nichts vorbereitet.</div></div>'}</div></section>${item?`<section class="wb-detail-pane"><header class="wb-detail-header"><div class="wb-detail-eyebrow"><span>${esc(item.status||'draft')}</span><span>${esc(item.signature_valid===false?'Signatur muss erneuert werden':'signiert')}</span></div><h2>${esc(item.subject||'(ohne Betreff)')}</h2><p>${esc(item.recipient||'')}</p></header><div class="wb-detail-body">${editing?`<div class="draft-editor"><label class="wb-editor-field"><span>Empfänger</span><input data-draft-recipient value="${esc(item.recipient||'')}"></label><label class="wb-editor-field"><span>Betreff</span><input data-draft-subject value="${esc(item.subject||'')}"></label><label class="wb-editor-field"><span>Nachricht</span><textarea data-draft-body>${esc(item.body||'')}</textarea></label></div>`:`<div class="wb-compose"><div class="wb-compose-line"><span>An</span><b>${esc(item.recipient||'—')}</b></div><div class="wb-compose-line"><span>Betreff</span><b>${esc(item.subject||'—')}</b></div><div class="wb-compose-body">${esc(item.body||'')}</div></div><div class="wb-detail-summary" style="margin-top:14px"><small>Signatur</small><p>Änderungen durch den Besitzer führen beim Speichern zu einem neuen Agent-ID-Stempel und werden als Besitzer-Feedback berücksichtigt.</p></div>`}</div><footer class="wb-detail-footer">${editing?`<button class="wb-btn" data-draft-cancel="${esc(item.draft_id)}">Abbrechen</button><button class="wb-btn primary" data-draft-save="${esc(item.draft_id)}">Speichern & neu signieren</button>`:`<button class="wb-btn" data-draft-edit="${esc(item.draft_id)}">Bearbeiten</button><button class="wb-btn primary" data-draft-submit="${esc(item.draft_id)}">Zur Freigabe geben</button>`}</footer></section>`:'<section class="wb-detail-pane"><div class="wb-empty"><div><b>Kein Entwurf ausgewählt</b></div></div></section>'}</div>`;
  }

  function renderAutomation() {
    const b = runtimeSettings?.behavior || {};
    const newsletter = b.newsletter_action || 'none';
    const advertising = b.advertising_action || 'none';
    const cold = b.cold_outreach_action || 'none';
    const option = (value,label,current,type) => `<button class="wb-choice ${current===value?'active':''}" data-auto-choice="${type}" data-auto-value="${value}">${label}</button>`;
    return `<div><div class="wb-section-head"><div><h2>Routinearbeit, aber unter deiner Kontrolle.</h2><p>Automationen sind explizite Regeln. MAIL-AGENT zeigt, was selbstständig passieren darf – und was nicht.</p></div><span class="wb-tag ${b.execution_mode==='shadow'?'warm':'green'}">${b.execution_mode==='shadow'?'Shadow Mode':'Live Mode'}</span></div><div class="wb-automation"><section class="wb-surface"><div class="wb-surface-head"><div><strong>Mail-Automationen</strong><small>Deterministische Nachbearbeitung nach der Analyse</small></div><button class="wb-btn primary" id="wb-save-automation">Speichern</button></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Newsletter</b><p>Eindeutig erkannte Newsletter ohne Rückfrage nach deiner Standardaktion behandeln.</p></div><span class="wb-tag">${newsletter==='none'?'Nur analysieren':newsletter==='mark_read'?'Als gelesen':'Archivieren'}</span></div><div class="wb-choice-line">${option('none','Nur analysieren',newsletter,'newsletter')}${option('mark_read','Als gelesen markieren',newsletter,'newsletter')}${option('archive','Archivieren, wenn Policy erlaubt',newsletter,'newsletter')}</div></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Werbung</b><p>Getrennt von Newslettern. Nur hohe Klassifikationssicherheit sollte automatisch handeln.</p></div><span class="wb-tag">${advertising==='none'?'Nur analysieren':advertising==='mark_read'?'Als gelesen':'Archivieren'}</span></div><div class="wb-choice-line">${option('none','Nur analysieren',advertising,'advertising')}${option('mark_read','Als gelesen markieren',advertising,'advertising')}${option('archive','Archivieren, wenn Policy erlaubt',advertising,'advertising')}</div></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Unaufgeforderte Vertriebsanfragen</b><p>Cold Outreach wird getrennt von Werbung erkannt. Bestehender Thread-Kontakt verhindert diese Einstufung.</p></div><span class="wb-tag">${cold==='none'?'Nur analysieren':cold==='mark_read'?'Als gelesen':'Archivieren'}</span></div><div class="wb-choice-line">${option('none','Nur analysieren',cold,'cold_outreach')}${option('mark_read','Als gelesen markieren',cold,'cold_outreach')}${option('archive','Archivieren, wenn Policy erlaubt',cold,'cold_outreach')}</div></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Follow-ups</b><p>Gesprächszustände werden automatisch verfolgt. Überfällige Threads können einen lokalen, weiterhin freigabepflichtigen Follow-up-Entwurf erhalten.</p></div><label class="wb-toggle"><input id="wb-followup-drafts" type="checkbox" ${b.follow_up_auto_draft!==false?'checked':''}><span></span></label></div><div class="wb-followup-grid"><label>Du bist dran nach <input id="wb-followup-to-reply" type="number" min="1" max="60" value="${esc(b.follow_up_to_reply_days??2)}"> Arbeitstagen</label><label>Warte auf andere nach <input id="wb-followup-awaiting" type="number" min="1" max="60" value="${esc(b.follow_up_awaiting_reply_days??4)}"> Arbeitstagen</label></div></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Abgearbeitete Nachrichten</b><p>Nach erfolgreicher Bearbeitung im echten Postfach als gelesen markieren. Fehler werden separat erneut versucht – ohne zweite LLM-Analyse.</p></div><label class="wb-toggle"><input id="wb-mark-processed-read" type="checkbox" ${b.mark_processed_read!==false?'checked':''}><span></span></label></div></div><div class="wb-rule-block"><div class="wb-rule-head"><div><b>Automatische Analyse</b><p>Neue Nachrichten im Zeitplan selbstständig in die Agenten-Queue übernehmen.</p></div><label class="wb-toggle"><input id="wb-auto-analyze" type="checkbox" ${b.auto_analyze_new_mail!==false?'checked':''}><span></span></label></div></div></section><aside class="wb-surface"><div class="wb-surface-head"><div><strong>Sicherheitsgrenzen</strong><small>gelten unabhängig von Automationen</small></div></div><div class="wb-side-note"><strong>Senden & Weiterleiten</strong>Bleiben freigabepflichtig. Eine Automationsregel kann diese Grenze nicht aufheben.</div><div class="wb-side-note"><strong>Löschen</strong>Bleibt High-Risk und nutzt sichere Trash-/Soft-Delete-Semantik.</div><div class="wb-side-note"><strong>Shadow Mode</strong>Unterbindet sämtliche produktiven Postfachänderungen – auch Mark-as-read und Archivieren.</div>${wb.patterns.length?`<div class="wb-patterns"><h4>Erkannte Sender-Muster</h4>${wb.patterns.slice(0,6).map(p=>`<div class="wb-pattern"><b>${esc(p.sender)}</b><span>${esc(p.matching_samples)}/${esc(p.samples)} × ${esc(p.category)} · ${Math.round(Number(p.confidence||0)*100)} %</span><div><button class="wb-btn" data-pattern-reject data-mailbox="${esc(p.mailbox_id)}" data-sender="${esc(p.sender)}" data-category="${esc(p.category)}">Verwerfen</button><button class="wb-btn primary" data-pattern-accept data-mailbox="${esc(p.mailbox_id)}" data-sender="${esc(p.sender)}" data-category="${esc(p.category)}">Als Regel übernehmen</button></div></div>`).join('')}</div>`:''}</aside></div></div>`;
  }

  function settingNav(label, section) { return `<button class="wb-settings-link ${wb.settingsSection===section?'active':''}" data-settings-panel="${section}">${esc(label)}</button>`; }
  function renderSettings() {
    const rs = runtimeSettings || {};
    const id = rs.identity || identity || {};
    const p = rs.profile || {};
    const b = rs.behavior || {};
    const provider = rs.provider || form.provider || 'ollama';
    const model = rs.model || form.model || 'default';
    const brain = brainStatus || {};
    let panel = '';
    if (wb.settingsSection === 'agent') panel = `<div class="wb-settings-title"><h2>Agent</h2><p>Identität, Ton und Autonomie. Sicherheitsgrenzen sind nicht Bestandteil der Persönlichkeit und bleiben technisch unveränderlich.</p></div><div class="wb-setting-section"><div class="wb-identity-grid"><div class="wb-identity-box"><small>Agent-ID</small><strong>${esc(id.agent_id||'—')}</strong></div><div class="wb-identity-box"><small>Fingerprint</small><strong>${esc(id.fingerprint||'—')}</strong></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Autonomie</b><p>Wie weit der Agent bei Low-Risk-Aktionen selbstständig arbeiten darf.</p></div><div class="wb-control"><select id="settings-autonomy"><option value="observer" ${p.autonomy_mode==='observer'?'selected':''}>Observer</option><option value="assistant" ${p.autonomy_mode==='assistant'?'selected':''}>Assistant</option><option value="copilot" ${p.autonomy_mode==='copilot'?'selected':''}>Copilot</option><option value="autonomous" ${p.autonomy_mode==='autonomous'?'selected':''}>Autonomous</option></select></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Ton</b><p>Sprachstil für Entwürfe.</p></div><div class="wb-control"><select id="settings-tone"><option value="friendly" ${p.tone==='friendly'?'selected':''}>Freundlich</option><option value="professional" ${p.tone==='professional'?'selected':''}>Professionell</option><option value="direct" ${p.tone==='direct'?'selected':''}>Direkt</option><option value="warm" ${p.tone==='warm'?'selected':''}>Warm</option></select></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Sprache</b></div><div class="wb-control"><select id="settings-language"><option value="de" ${p.language!=='en'?'selected':''}>Deutsch</option><option value="en" ${p.language==='en'?'selected':''}>English</option></select></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Persönliche Signatur</b><p>Steht vor der technisch verpflichtenden Agent-ID-Signatur.</p></div><div class="wb-control"><textarea id="settings-email-signature" rows="5">${esc(p.email_signature||'')}</textarea></div></div><div class="wb-settings-actions"><button class="wb-btn primary" id="settings-save-profile">Agent speichern</button></div></div>`;
    if (wb.settingsSection === 'model') panel = `<div class="wb-settings-title"><h2>Modelle</h2><p>MAIL-AGENT trennt Modellwahl von Sicherheitslogik. Ein Modell kann Vorschläge erzeugen, aber keine Policy umgehen.</p></div><div class="wb-setting-section"><div class="wb-setting-row"><div class="wb-setting-label"><b>Provider</b><p>Ollama arbeitet lokal; Codex nutzt den offiziellen ChatGPT-Login.</p></div><div class="wb-control"><select id="settings-provider"><option value="ollama" ${provider==='ollama'?'selected':''}>Ollama · lokal</option><option value="codex" ${provider==='codex'?'selected':''}>ChatGPT / OpenAI · Codex CLI</option></select></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Modell</b><p>Automatisch gefundene Modelle werden bevorzugt angeboten.</p></div><div class="wb-control"><select id="settings-model">${[...(rs.providers?.[provider]?.models||[]), ...(provider==='codex'?['default']:[])].filter((v,i,a)=>v&&a.indexOf(v)===i).map(m=>`<option value="${esc(m)}" ${m===model?'selected':''}>${esc(provider==='codex'&&m==='default'?'Automatisch (Codex-Standard)':m)}</option>`).join('') || `<option value="${esc(model)}" selected>${esc(model)}</option>`}</select></div></div><div class="wb-settings-actions"><button class="wb-btn" id="settings-provider-test">Provider prüfen</button>${provider==='codex'?'<button class="wb-btn" id="settings-chatgpt-login">Mit ChatGPT anmelden</button>':''}<button class="wb-btn primary" id="settings-save-llm">Modell speichern</button></div></div>`;
    if (wb.settingsSection === 'brain') panel = `<div class="wb-settings-title"><h2>Gedächtnis</h2><p>SOUL und MEMORY beeinflussen Verhalten, aber niemals Policy, Freigaben oder Agent-ID.</p></div><div class="wb-setting-section"><div class="wb-setting-row"><div class="wb-setting-label"><b>SOUL.md</b><p>Arbeitsidentität und Prinzipien des Agenten.</p></div><div class="wb-control"><textarea id="brain-soul" rows="15">${esc(brain.soul||'')}</textarea></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>MEMORY.md</b><p>Dauerhaftes Besitzerwissen. Fremde Mails schreiben hier niemals direkt hinein.</p></div><div class="wb-control"><textarea id="brain-memory" rows="15">${esc(brain.memory||'')}</textarea></div></div><div class="wb-settings-actions"><button class="wb-btn" id="settings-refresh-brain">Neu laden</button><button class="wb-btn primary" id="settings-save-brain">Speichern</button></div></div>`;
    if (wb.settingsSection === 'behavior') panel = `<div class="wb-settings-title"><h2>Arbeitsweise</h2><p>Zeitplan, Queue-Größe und automatische Entwürfe. Newsletter/Werbung liegen im eigenen Bereich „Automationen“.</p></div><div class="wb-setting-section"><div class="wb-setting-row"><div class="wb-setting-label"><b>Agent aktiv</b></div><div class="wb-control"><label class="wb-toggle"><input id="behavior-enabled" type="checkbox" ${b.enabled!==false?'checked':''}><span></span></label></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Ausführungsmodus</b><p>Shadow Mode simuliert alles ohne Side Effects.</p></div><div class="wb-control"><select id="behavior-execution-mode"><option value="live" ${b.execution_mode!=='shadow'?'selected':''}>Live</option><option value="shadow" ${b.execution_mode==='shadow'?'selected':''}>Shadow</option></select></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Antwortentwürfe</b></div><div class="wb-control"><label class="wb-toggle"><input id="behavior-auto-drafts" type="checkbox" ${b.auto_create_drafts!==false?'checked':''}><span></span></label></div></div><input id="behavior-auto-analyze" type="checkbox" ${b.auto_analyze_new_mail!==false?'checked':''} hidden><input id="behavior-confidence" value="${esc(b.minimum_confidence??.72)}" hidden><input id="behavior-max-messages" value="${esc(b.max_messages_per_cycle??20)}" hidden><div class="wb-setting-row"><div class="wb-setting-label"><b>Arbeitszeit</b><p>Außerhalb dieses Fensters werden keine automatischen Zyklen gestartet.</p></div><div class="wb-control wb-time-pair"><input id="behavior-from" type="time" value="${esc(b.active_from||'00:00')}"><span>bis</span><input id="behavior-until" type="time" value="${esc(b.active_until||'23:59')}"></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Aktive Tage</b></div><div class="wb-control wb-days">${[['Mo',0],['Di',1],['Mi',2],['Do',3],['Fr',4],['Sa',5],['So',6]].map(([label,day])=>`<label><input type="checkbox" data-agent-day="${day}" ${(b.active_days||[]).includes(day)?'checked':''}><span>${label}</span></label>`).join('')}</div></div><label class="wb-editor-field"><span>Nie automatisch bearbeiten · Absender oder Domain</span><textarea id="behavior-blocked-senders" rows="4" placeholder="newsletter@example.com\n@example.org">${esc((b.never_auto_act_senders||[]).join('\n'))}</textarea></label><div class="wb-setting-row"><div class="wb-setting-label"><b>Mindest-Konfidenz</b><p>Unterhalb davon keine automatische Low-Risk-Aktion.</p></div><div class="wb-control"><input id="wb-behavior-confidence" type="number" min="0" max="1" step="0.01" value="${esc(b.minimum_confidence??.72)}"></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Max. Mails pro Zyklus</b></div><div class="wb-control"><input id="wb-behavior-max" type="number" min="1" max="200" value="${esc(b.max_messages_per_cycle??20)}"></div></div><div class="wb-settings-actions"><button class="wb-btn primary" id="wb-save-behavior">Arbeitsweise speichern</button></div></div>`;
    if (wb.settingsSection === 'rules') {
      const rules = b.rules || [];
      panel = `<div class="wb-settings-title"><h2>Regeln</h2><p>Absender und Domains deterministisch steuern. Diese Regeln werden nach der Modellanalyse im Gateway erzwungen.</p></div><div class="wb-setting-section"><div class="wb-settings-actions top"><button class="wb-btn" id="settings-add-rule">Regel hinzufügen</button><button class="wb-btn primary" id="wb-save-rules">Regeln speichern</button></div><div class="rule-editor wb-rule-editor">${rules.length?rules.map(ruleRow).join(''):'<div class="wb-empty compact"><div><b>Noch keine speziellen Regeln</b>Neue Regeln können Absender oder ganze Domains deterministisch behandeln.</div></div>'}</div></div>`;
    }
    if (wb.settingsSection === 'software') {
      const current = updateStatus?.current_version || '0.15.0';
      const available = !!updateStatus?.available;
      panel = `<div class="wb-settings-title"><h2>Software</h2><p>Update-Kanal, installierte Version und verifizierter In-Place-Updater.</p></div><div class="wb-setting-section"><div class="wb-setting-row"><div class="wb-setting-label"><b>Installierte Version</b></div><div class="wb-control"><span class="wb-tag">v${esc(current)}</span></div></div><div class="wb-setting-row"><div class="wb-setting-label"><b>Update-Kanal</b><p>Installer wird per SHA-256 und Release-Digest geprüft.</p></div><div class="wb-control">${esc(updateStatus?.channel||'Preview')}</div></div><div class="wb-settings-actions"><button class="wb-btn" id="check-update">Jetzt nach Updates suchen</button>${available?'<button class="wb-btn primary" id="install-update">Update installieren</button>':''}</div>${updateStatus?.error?`<div class="wb-side-note"><strong>Update-Kanal nicht erreichbar</strong>${esc(updateStatus.error)}</div>`:''}</div>`;
      if (!updateStatus && !updateLoading) setTimeout(()=>checkUpdate(true),0);
    }
    if (wb.settingsSection === 'security') panel = `<div class="wb-settings-title"><h2>Sicherheit</h2><p>Die Grenzen sind bewusst nicht als Toggles gestaltet: Was unverhandelbar ist, sieht auch unverhandelbar aus.</p></div><div class="wb-setting-section wb-security-list"><div class="wb-security-item">${icon('lock',18)}<div><b>Lokaler Credential Vault</b><p>OAuth-Tokens, Mailbox-Secrets und Agent-Schlüssel bleiben lokal verschlüsselt.</p></div></div><div class="wb-security-item">${icon('shield',18)}<div><b>Policy Engine vor jeder Ausführung</b><p>Das LLM schlägt nur vor. Deterministische Regeln entscheiden, ob eine Aktion erlaubt ist.</p></div></div><div class="wb-security-item">${icon('mail',18)}<div><b>Senden / Weiterleiten approval-gated</b><p>Outbound bleibt menschlich freigabepflichtig.</p></div></div><div class="wb-security-item">${icon('shield',18)}<div><b>Agent-ID nicht abschaltbar</b><p>Ausgehende Agentenkommunikation bleibt ihrem Besitzer und dieser Installation zuordenbar.</p></div></div></div>`;
    return `<div class="wb-settings"><nav class="wb-settings-nav"><h3>Agent & Regeln</h3>${settingNav('Agent','agent')}${settingNav('Modelle','model')}${settingNav('Gedächtnis','brain')}${settingNav('Arbeitsweise','behavior')}${settingNav('Regeln','rules')}${settingNav('Sicherheit','security')}${settingNav('Software','software')}</nav><section class="wb-settings-main">${panel}</section></div>`;
  }

  function renderSystem() {
    const h = systemHealth || {};
    const checks = h.checks || [];
    const summary = h.summary || {};
    return `<div><div class="wb-section-head"><div><h2>${h.overall==='ok'?'System bereit':'Systemzustand prüfen'}</h2><p>Technische Details bleiben verfügbar, stehen aber nicht im Weg, solange alles gesund ist.</p></div><button class="wb-btn" id="system-health-refresh">System prüfen</button></div><div class="wb-kpis"><div class="wb-kpi"><small>Bereit</small><strong>${summary.ok||0}</strong><span>Checks erfolgreich</span></div><div class="wb-kpi"><small>Warnungen</small><strong>${summary.warning||0}</strong><span>weiter funktionsfähig</span></div><div class="wb-kpi"><small>Fehler</small><strong>${summary.error||0}</strong><span>Aktion erforderlich</span></div><div class="wb-kpi"><small>Geprüft</small><strong>${fmtTime(h.checked_at)}</strong><span>lokale Diagnose</span></div></div><section class="wb-surface" style="margin-top:14px"><div class="wb-surface-head"><div><strong>Komponenten</strong><small>Recovery-Aktionen erscheinen nur bei Bedarf</small></div><span class="wb-tag ${h.overall==='ok'?'green':'warm'}">${esc(h.overall||'checking')}</span></div>${checks.length?checks.map(c=>`<div class="wb-focus-row"><span class="wb-focus-bar ${c.status==='error'?'urgent':c.status==='warning'?'normal':'low'}"></span><div class="wb-focus-copy"><b>${esc(c.id||'Prüfung')}</b><p>${esc(c.detail||'')}</p></div><div class="wb-focus-meta"><span class="wb-tag ${c.status==='ok'?'green':c.status==='error'?'red':'warm'}">${esc(c.status||'')}</span>${c.action?`<button class="wb-btn" data-health-action="${esc(c.action)}" data-health-mailbox="${esc(c.data?.mailbox_id||'')}">Öffnen</button>`:''}</div></div>`).join(''):'<div class="wb-empty"><div><b>Noch keine Diagnose</b>Starte eine Systemprüfung.</div></div>'}</section></div>`;
  }

  renderDashboard = function workbenchRenderDashboard() {
    let content = '';
    if (activeView === 'overview') content = renderBriefing();
    if (activeView === 'inbox') content = renderInbox();
    if (activeView === 'attention') content = renderAttention();
    if (activeView === 'waiting') content = renderWaiting();
    if (activeView === 'approvals') content = renderApprovals();
    if (activeView === 'drafts') content = renderDrafts();
    if (activeView === 'automation') content = renderAutomation();
    if (activeView === 'activity') content = renderActivityCenter();
    if (activeView === 'shadow') content = renderShadowCenter();
    if (activeView === 'settings') content = renderSettings();
    if (activeView === 'system') content = renderSystem();
    app.innerHTML = dashboardLayout(content);
    bindDashboard();
    bindWorkbench();
  };

  // Replace dashboard binding while keeping original production actions.
  const originalBindDashboard = bindDashboard;
  bindDashboard = function workbenchBindDashboard() {
    originalBindDashboard();
    document.querySelectorAll('[data-view]').forEach(el => {
      el.onclick = async event => {
        const view = el.dataset.view;
        const section = el.dataset.settingsSection;
        if (section) wb.settingsSection = section;
        activeView = view;
        history.replaceState({}, '', view === 'overview' ? '/' : `/?view=${encodeURIComponent(view)}`);
        if (view === 'attention') await loadAttention(true);
        if (['overview','waiting','automation'].includes(view)) await loadConversationIntelligence(true);
        if (['settings','automation','activity','shadow','system'].includes(view)) await Promise.all([
          runtimeSettings ? Promise.resolve() : loadRuntimeSettings(true),
          loadBrainStatus(true),
          view === 'shadow' ? loadShadowStatus(true) : Promise.resolve(),
          view === 'system' ? loadSystemHealth(true) : Promise.resolve(),
        ]);
        render();
      };
    });
  };

  async function saveAutomation() {
    try {
      const latest = await get('/v1/settings');
      const next = {...(latest.behavior||{}),
        mark_processed_read: !!document.getElementById('wb-mark-processed-read')?.checked,
        auto_analyze_new_mail: !!document.getElementById('wb-auto-analyze')?.checked,
        newsletter_action: document.querySelector('[data-auto-choice="newsletter"].active')?.dataset.autoValue || 'none',
        advertising_action: document.querySelector('[data-auto-choice="advertising"].active')?.dataset.autoValue || 'none',
        cold_outreach_action: document.querySelector('[data-auto-choice="cold_outreach"].active')?.dataset.autoValue || 'none',
        follow_up_auto_draft: !!document.getElementById('wb-followup-drafts')?.checked,
        follow_up_to_reply_days: Number(document.getElementById('wb-followup-to-reply')?.value || 2),
        follow_up_awaiting_reply_days: Number(document.getElementById('wb-followup-awaiting')?.value || 4),
      };
      runtimeSettings = await put('/v1/settings/behavior',{behavior:next});
      showNotice('Automationen gespeichert.');
      render();
    } catch (error) { showNotice(error.message,'error'); }
  }

  async function saveRules() {
    try {
      const latest = await get('/v1/settings');
      const next = {...(latest.behavior||{}), rules: collectRuleRows()};
      runtimeSettings = await put('/v1/settings/behavior',{behavior:next});
      showNotice('Regeln gespeichert.');
      render();
    } catch (error) { showNotice(error.message,'error'); }
  }

  function commandItems() {
    const items = [
      ['overview','Briefing öffnen','Arbeitslage und Prioritäten'],['inbox','Eingang öffnen','Synchronisierte Nachrichten'],['attention','Wartet auf dich','Offene Rückfragen'],['waiting','Wartet auf andere','Follow-ups und ausstehende Antworten'],['approvals','Freigaben öffnen','Riskante Aktionen prüfen'],['drafts','Entwürfe öffnen','Vorbereitete Antworten'],['automation','Automationen öffnen','Newsletter und Werbung'],['activity','Journal öffnen','Agentenaktivität'],['shadow','Testlabor öffnen','Shadow Mode und Simulation'],['settings','Agent & Regeln','Konfiguration'],['system','System öffnen','Gesundheit und Recovery'],
    ];
    for (const m of (dashboard.messages||[]).slice(0,30)) items.push(['inbox', clean(m.subject||'(ohne Betreff)'), clean(m.sender||'Nachricht')]);
    return items;
  }

  function closeCommand() { document.getElementById('wb-command-palette')?.remove(); wb.commandOpen=false; }
  function openCommand() {
    if (wb.commandOpen) return; wb.commandOpen=true;
    const overlay=document.createElement('div'); overlay.id='wb-command-palette'; overlay.className='wb-command-overlay';
    overlay.innerHTML=`<div class="wb-command-dialog"><div class="wb-command-input">${icon('spark',16)}<input id="wb-command-input" placeholder="Bereich, Mail oder Aktion suchen …" autocomplete="off"><kbd>Esc</kbd></div><div class="wb-command-results" id="wb-command-results"></div><div class="wb-command-footer"><button data-command-action="sync">Postfach synchronisieren</button><button data-command-action="run">Agent ausführen</button></div></div>`;
    document.body.appendChild(overlay);
    const input=overlay.querySelector('#wb-command-input'), results=overlay.querySelector('#wb-command-results');
    const paint=()=>{const q=clean(input.value).toLowerCase();const found=commandItems().filter(x=>!q||`${x[1]} ${x[2]}`.toLowerCase().includes(q)).slice(0,12);results.innerHTML=found.map(x=>`<button data-command-view="${esc(x[0])}"><b>${esc(x[1])}</b><span>${esc(x[2])}</span></button>`).join('')||'<div class="wb-command-empty">Keine Treffer</div>';};
    input.addEventListener('input',paint); paint(); input.focus();
    overlay.addEventListener('click',async e=>{if(e.target===overlay){closeCommand();return;}const view=e.target.closest('[data-command-view]')?.dataset.commandView;if(view){activeView=view;closeCommand();if(view==='attention')await loadAttention(true);render();return;}const action=e.target.closest('[data-command-action]')?.dataset.commandAction;if(action==='sync'){closeCommand();syncNow();}if(action==='run'){closeCommand();runAgentNow();}});
  }

  function bindWorkbench() {
    document.getElementById('wb-run-agent')?.addEventListener('click', runAgentNow);
    document.getElementById('wb-run-agent-context')?.addEventListener('click', runAgentNow);
    document.getElementById('wb-command-search')?.addEventListener('click', openCommand);
    document.querySelectorAll('[data-inbox-filter]').forEach(el=>el.addEventListener('click',()=>{wb.inboxFilter=el.dataset.inboxFilter;wb.selectedMessage=0;render();}));
    document.querySelectorAll('[data-attention-filter]').forEach(el=>el.addEventListener('click',()=>{wb.attentionFilter=el.dataset.attentionFilter;wb.selectedAttention=0;render();}));
    document.querySelectorAll('[data-mail-select]').forEach(el => el.addEventListener('click',()=>{wb.selectedMessage=Number(el.dataset.mailSelect);render();}));
    document.querySelectorAll('[data-attention-select]').forEach(el => el.addEventListener('click',()=>{wb.selectedAttention=Number(el.dataset.attentionSelect);render();}));
    document.querySelectorAll('[data-waiting-select]').forEach(el => el.addEventListener('click',()=>{wb.selectedWaiting=Number(el.dataset.waitingSelect);render();}));
    document.querySelectorAll('[data-approval-select]').forEach(el => el.addEventListener('click',()=>{wb.selectedApproval=Number(el.dataset.approvalSelect);render();}));
    document.querySelectorAll('[data-draft-select]').forEach(el => el.addEventListener('click',()=>{wb.selectedDraft=Number(el.dataset.draftSelect);render();}));
    document.querySelectorAll('[data-settings-panel]').forEach(el => el.addEventListener('click',()=>{wb.settingsSection=el.dataset.settingsPanel;render();}));
    document.querySelectorAll('[data-auto-choice]').forEach(el => el.addEventListener('click',()=>{
      const type=el.dataset.autoChoice;
      document.querySelectorAll(`[data-auto-choice="${type}"]`).forEach(x=>x.classList.remove('active'));
      el.classList.add('active');
    }));
    document.getElementById('wb-save-automation')?.addEventListener('click',saveAutomation);
    document.getElementById('wb-save-rules')?.addEventListener('click',saveRules);
    document.getElementById('wb-save-behavior')?.addEventListener('click',()=>{
      const c=document.getElementById('wb-behavior-confidence'); const m=document.getElementById('wb-behavior-max');
      if(c)document.getElementById('behavior-confidence').value=c.value;
      if(m)document.getElementById('behavior-max-messages').value=m.value;
      saveBehaviorSettings();
    });
    document.querySelectorAll('[data-attention-resolve]').forEach(button=>button.addEventListener('click',async()=>{
      const id=button.dataset.attentionResolve, mailboxId=button.dataset.mailbox;
      const note=document.querySelector(`[data-attention-note="${CSS.escape(id)}"]`)?.value?.trim()||null;
      try{await post('/v1/attention/resolve',{mailbox_id:mailboxId,message_id:id,owner_note:note,actor:'local-user'});await loadAttention(true);showNotice('Rückfrage erledigt.');render();}catch(error){showNotice(error.message,'error');}
    }));

    document.querySelectorAll('[data-snooze-thread]').forEach(button=>button.addEventListener('click',async()=>{
      const until=new Date(Date.now()+Number(button.dataset.hours||24)*3600000).toISOString();
      try{await post('/v1/conversations/snooze',{mailbox_id:button.dataset.mailbox,thread_id:button.dataset.snoozeThread,until,actor:'local-user'});await loadConversationIntelligence(true);showNotice('Wiedervorlage gespeichert.');render();}catch(error){showNotice(error.message,'error');}
    }));
    document.querySelectorAll('[data-pattern-accept]').forEach(button=>button.addEventListener('click',async()=>{
      try{await post('/v1/sender-patterns/accept',{mailbox_id:button.dataset.mailbox,sender:button.dataset.sender,category:button.dataset.category,actor:'local-user'});await loadConversationIntelligence(true);showNotice('Sender-Muster als Regel übernommen.');render();}catch(error){showNotice(error.message,'error');}
    }));
    document.querySelectorAll('[data-pattern-reject]').forEach(button=>button.addEventListener('click',async()=>{
      try{await post('/v1/sender-patterns/reject',{mailbox_id:button.dataset.mailbox,sender:button.dataset.sender,category:button.dataset.category,actor:'local-user'});await loadConversationIntelligence(true);showNotice('Muster verworfen.');render();}catch(error){showNotice(error.message,'error');}
    }));
    document.querySelectorAll('[data-undo-token]').forEach(button=>button.addEventListener('click',async()=>{
      try{await post(`/v1/actions/undo/${encodeURIComponent(button.dataset.undoToken)}`,{actor:'local-user'});showNotice('Mailbox-Aktion rückgängig gemacht.');await loadDashboard(true);render();}catch(error){showNotice(error.message,'error');}
    }));
    if (!window.__mailAgentWorkbenchKeysBound) { window.__mailAgentWorkbenchKeysBound=true; document.addEventListener('keydown',event=>{ if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openCommand();} if(event.key==='Escape') closeCommand(); }); }
  }

  // The original enhancement is deliberately replaced; attention is now a first-class work area.
  window.__mailAgentWorkbench = wb;

  // Real installed systems load attention quietly; fresh setup remains untouched.
  setTimeout(async()=>{ if (installed) { await Promise.all([loadAttention(true),loadConversationIntelligence(true)]); render(); } }, 450);
})();
