(() => {
  const existingNotice = showNotice;

  function persistentErrorMessage(value) {
    const text = String(value || '').trim();
    if (!text) return 'Die Aktion konnte nicht abgeschlossen werden.';
    if (/403 forbidden/i.test(text) && /calendar|google/i.test(text)) {
      return 'Google Kalender hat den Zugriff verweigert. Prüfe die Calendar-Berechtigungen bzw. ob die Google Calendar API aktiviert ist.';
    }
    if (/401|unauthori[sz]ed/i.test(text) && /calendar|google/i.test(text)) {
      return 'Die Google-Kalender-Anmeldung ist nicht mehr gültig. Bitte Kalender erneut verbinden.';
    }
    if (/failed to fetch|networkerror|econnrefused|connection refused/i.test(text)) {
      return 'MAIL-AGENT oder Google Calendar ist gerade nicht erreichbar. Prüfe die Verbindung und versuche es erneut.';
    }
    return text;
  }

  showNotice = function v171Notice(text, kind='success') {
    if (kind !== 'error') return existingNotice(text, kind);
    notice.textContent = persistentErrorMessage(text);
    notice.className = 'toast error';
    clearTimeout(showNotice.timer);
    showNotice.timer = setTimeout(() => notice.className = 'toast hidden', 12000);
  };

  // Drafts are owner work items. They can now be explicitly discarded instead of accumulating.
  const previousDraftCard = draftCard;
  draftCard = function v171DraftCard(item) {
    let markup = previousDraftCard(item);
    if (editingDraftId === item.draft_id || ['sent','discarded'].includes(String(item.status || ''))) return markup;
    const label = item.approval_id ? 'Ablehnen & verwerfen' : 'Verwerfen';
    const button = `<button class="btn text compact v171-discard" data-draft-discard="${esc(item.draft_id)}">${icon('x',15)} ${label}</button>`;
    const end = markup.lastIndexOf('</div></article>');
    return end >= 0 ? `${markup.slice(0,end)}${button}${markup.slice(end)}` : markup;
  };

  async function discardDraft(id) {
    const item = (dashboard.drafts || []).find(d => d.draft_id === id);
    const question = item?.approval_id
      ? 'Diesen Entwurf und seine offene Freigabe wirklich ablehnen und verwerfen?'
      : 'Diesen Entwurf wirklich verwerfen?';
    if (!window.confirm(question)) return;
    try {
      await post(`/v1/drafts/${encodeURIComponent(id)}/discard`, {actor:'local-user'});
      if (editingDraftId === id) editingDraftId = null;
      await loadDashboard(true);
      showNotice('Entwurf verworfen.');
      render();
    } catch (error) {
      showNotice(error.message, 'error');
    }
  }

  const previousBindDashboard = bindDashboard;
  bindDashboard = function v171BindDashboard() {
    previousBindDashboard();
    document.querySelectorAll('[data-draft-discard]').forEach(button => {
      button.onclick = () => discardDraft(button.dataset.draftDiscard);
    });
  };

  const cal = window.__mailAgentCalendar || {};
  const simple = {
    loaded: false,
    loading: false,
    error: '',
    status: null,
    mailboxId: '',
    calendars: [],
    calendarId: 'primary',
    briefing: null,
    events: [],
    approvals: [],
    suggestions: [],
    result: null,
    sourceMessageId: cal.sourceMessageId || '',
    sourceSubject: cal.sourceSubject || '',
    details: false,
  };

  function html(value='') { return esc(String(value ?? '')); }
  function eventStart(item) { return item?.start?.dateTime || item?.start?.date || ''; }
  function eventEnd(item) { return item?.end?.dateTime || item?.end?.date || ''; }
  function fmt(value) {
    if (!value) return '—';
    try { return new Date(value).toLocaleString('de-DE', {dateStyle:'medium', timeStyle:'short'}); }
    catch (_) { return String(value); }
  }
  function account() {
    return (simple.status?.accounts || []).find(x => x.mailbox_id === simple.mailboxId)
      || (simple.status?.accounts || []).find(x => x.connected)
      || simple.status?.accounts?.[0]
      || null;
  }

  async function api(path, options={}) {
    const response = await fetch(path, {
      cache:'no-store',
      headers:{'Content-Type':'application/json', ...(options.headers||{})},
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || JSON.stringify(payload.detail || {});
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  async function loadSimple(force=false) {
    if (simple.loading && !force) return;
    simple.loading = true;
    simple.error = '';
    try {
      simple.status = await api('/v1/calendar/status');
      const acct = account();
      if (!simple.mailboxId && acct) simple.mailboxId = acct.mailbox_id;
      if (!acct?.connected) {
        simple.loaded = true;
        return;
      }
      const calendars = await api(`/v1/calendar/calendars?mailbox_id=${encodeURIComponent(simple.mailboxId)}`);
      simple.calendars = calendars.calendars || [];
      if (!simple.calendars.some(item => String(item.id) === String(simple.calendarId))) {
        simple.calendarId = simple.calendars.find(item => item.primary)?.id || simple.calendars[0]?.id || 'primary';
      }
      const [briefing, events, approvals, suggestions] = await Promise.all([
        api(`/v1/calendar/briefing?mailbox_id=${encodeURIComponent(simple.mailboxId)}&calendar_id=${encodeURIComponent(simple.calendarId)}&duration_minutes=60`),
        api(`/v1/calendar/events?mailbox_id=${encodeURIComponent(simple.mailboxId)}&calendar_id=${encodeURIComponent(simple.calendarId)}&max_results=30`),
        api('/v1/calendar/approvals?status=pending&limit=30'),
        api(`/v1/calendar/mail-suggestions?mailbox_id=${encodeURIComponent(simple.mailboxId)}&limit=80`).catch(()=>({suggestions:[]})),
      ]);
      simple.briefing = briefing;
      simple.events = events.events || [];
      simple.approvals = approvals.approvals || [];
      simple.suggestions = suggestions.suggestions || [];
      simple.loaded = true;
      cal.mailboxId = simple.mailboxId;
      cal.calendarId = simple.calendarId;
    } catch (error) {
      simple.loaded = true;
      simple.error = persistentErrorMessage(error.message);
    } finally {
      simple.loading = false;
    }
  }

  function ensureStyles() {
    if (document.getElementById('v171-ux-styles')) return;
    const style = document.createElement('style');
    style.id = 'v171-ux-styles';
    style.textContent = `
      .v171-discard{color:#f1a7b1!important}.su-shell{display:grid;gap:14px;max-width:1180px}.su-hero,.su-card{border:1px solid #26364d;background:#0d1725;border-radius:17px;padding:18px}.su-hero{padding:22px}.su-hero h2{font-size:25px;margin:4px 0 7px}.su-hero p,.su-muted{color:#8ea1bd;line-height:1.5}.su-kicker{font-size:11px;letter-spacing:.12em;color:#7992b7}.su-status{display:inline-flex;padding:5px 9px;border:1px solid #314760;border-radius:99px;font-size:11px;color:#9bd7b2}.su-compose{display:grid;gap:10px}.su-input{width:100%;box-sizing:border-box;background:#081321;border:1px solid #2b3d57;border-radius:12px;color:#edf3ff;padding:13px;min-height:100px;resize:vertical}.su-actions{display:flex;gap:8px;flex-wrap:wrap}.su-btn{border:1px solid #344a67;background:#122239;color:#eaf2ff;border-radius:9px;padding:9px 12px;cursor:pointer}.su-btn.primary{background:#edf2fb;color:#0b1421;border-color:#edf2fb;font-weight:700}.su-btn.danger{color:#ffc0c8;border-color:#6a3742;background:#25151a}.su-source{border:1px solid #3e597a;background:#0a192a;border-radius:11px;padding:10px;font-size:12px}.su-result{border:1px solid #365273;border-radius:13px;padding:15px;background:#0a1625}.su-result.good{border-color:#38654c}.su-result.busy{border-color:#73543a}.su-result h3{margin:0 0 7px}.su-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.su-row{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 0;border-top:1px solid #1f2e43}.su-row:first-child{border-top:0}.su-row b{display:block}.su-row small{display:block;color:#8397b5;margin-top:4px}.su-pill{display:inline-flex;padding:4px 8px;border:1px solid #30455f;border-radius:99px;font-size:10px;color:#aabbd2}.su-summary{display:flex;gap:10px;flex-wrap:wrap}.su-summary span{border:1px solid #283b55;border-radius:11px;padding:9px 11px;color:#aabbd2;font-size:12px}.su-error{border:1px solid #773d48;background:#271419;color:#ffc0c8;border-radius:12px;padding:13px}.su-details summary{cursor:pointer;color:#aabbd2}.su-select{background:#081321;border:1px solid #2b3d57;color:#edf3ff;border-radius:9px;padding:8px 10px}.su-empty{color:#8397b5;padding:8px 0}@media(max-width:900px){.su-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function disconnectedPage() {
    return `<div class="su-shell"><section class="su-hero"><span class="su-kicker">KALENDER-ASSISTENT</span><h2>Google Kalender verbinden</h2><p>Danach prüft MAIL-AGENT Terminanfragen, findet Konflikte und bereitet Änderungen für dich vor.</p><div class="su-actions" style="margin-top:14px"><button class="su-btn primary" id="su-connect">Google Kalender verbinden</button></div></section>${simple.error?`<div class="su-error">${html(simple.error)}</div>`:''}</div>`;
  }

  function resultCard() {
    const result = simple.result;
    if (!result) return '';
    const check = result.requested_time_check;
    const cls = check ? (check.is_free ? 'good' : 'busy') : '';
    const title = result.kind === 'proposal' ? 'Vorbereitet – deine Freigabe fehlt noch' : check?.is_free ? 'Der Termin passt' : check && !check.is_free ? 'Der Termin kollidiert' : 'Antwort';
    const prepare = check?.is_free && simple.sourceMessageId && result.kind !== 'proposal'
      ? `<button class="su-btn primary" id="su-prepare-target">Termin zur Freigabe vorbereiten</button>` : '';
    return `<section class="su-result ${cls}"><h3>${html(title)}</h3><div>${html(result.answer||'')}</div>${prepare?`<div class="su-actions" style="margin-top:12px">${prepare}</div>`:''}</section>`;
  }

  function calendarPage() {
    ensureStyles();
    if (!simple.loaded) {
      window.setTimeout(async()=>{await loadSimple(); if(activeView==='calendar')render();},0);
      return '<div class="su-shell"><section class="su-card"><div class="su-empty">Kalender wird vorbereitet …</div></section></div>';
    }
    if (!account()?.connected) return disconnectedPage();
    const briefing = simple.briefing || {};
    const today = briefing.today_events || [];
    const next = briefing.next_event;
    const source = simple.sourceMessageId
      ? `<div class="su-source"><b>Terminanfrage aus Mail</b><br>${html(simple.sourceSubject||simple.sourceMessageId)} <button class="su-btn" id="su-source-clear" style="margin-left:8px">Entfernen</button></div>` : '';
    const suggestions = simple.suggestions.slice(0,5).map((item,index)=>`<div class="su-row"><div><b>${html(item.subject||'(ohne Betreff)')}</b><small>${html(item.sender||'')} · ${item.has_explicit_time?'konkreter Termin erkannt':'Terminbezug erkannt'}</small></div><button class="su-btn primary" data-su-mail="${index}">Prüfen</button></div>`).join('');
    const upcoming = simple.events.slice(0,5).map(item=>`<div class="su-row"><div><b>${html(item.summary||'(ohne Titel)')}</b><small>${html(fmt(eventStart(item)))} – ${html(fmt(eventEnd(item)))}</small></div></div>`).join('');
    const approvals = simple.approvals.map(item=>`<div class="su-row"><div><b>${html(item.proposal?.event?.summary||item.action)}</b><small>${html(item.action)} · wartet auf deine Entscheidung</small></div><div class="su-actions"><button class="su-btn danger" data-su-reject="${html(item.approval_id)}">Ablehnen</button><button class="su-btn primary" data-su-approve="${html(item.approval_id)}">Freigeben</button></div></div>`).join('');
    return `<div class="su-shell">
      <section class="su-hero"><span class="su-kicker">KALENDER-ASSISTENT · 0.17.1</span><h2>Was soll ich für dich erledigen?</h2><p>Du beschreibst das Ziel. MAIL-AGENT prüft die echten Kalenderdaten und zeigt dir nur die Entscheidung, die du treffen musst.</p><div class="su-summary" style="margin-top:14px"><span>${today.length} Termine heute</span><span>${next?`Nächster: ${html(next.summary||'(ohne Titel)')} · ${html(fmt(eventStart(next)))}`:'Heute nichts mehr geplant'}</span>${simple.approvals.length?`<span>${simple.approvals.length} Freigabe${simple.approvals.length===1?'':'n'} offen</span>`:''}<span class="su-status">Google verbunden</span></div></section>
      ${simple.error?`<div class="su-error">${html(simple.error)}</div>`:''}
      <section class="su-card su-compose">${source}<textarea class="su-input" id="su-instruction" placeholder="z. B. Prüfe die Terminanfrage aus der Mail · Wann habe ich morgen eine Stunde frei? · Trag den vorgeschlagenen Termin ein"></textarea><div class="su-actions"><button class="su-btn" data-su-quick="Was steht heute noch in meinem Kalender?">Heute</button><button class="su-btn" data-su-quick="Wann habe ich morgen 60 Minuten frei?">Morgen frei?</button><button class="su-btn primary" id="su-run">Prüfen & vorbereiten</button></div>${resultCard()}</section>
      ${simple.suggestions.length?`<section class="su-card"><h3 style="margin-top:0">Terminanfragen aus deinen Mails</h3><p class="su-muted">Ein Klick genügt: Der konkrete angefragte Zeitpunkt wird zuerst geprüft – auch am Wochenende.</p>${suggestions}</section>`:''}
      <div class="su-grid"><section class="su-card"><h3 style="margin-top:0">Nächste Termine</h3>${upcoming||'<div class="su-empty">Keine kommenden Termine.</div>'}</section><section class="su-card"><h3 style="margin-top:0">${simple.approvals.length?'Deine Entscheidungen':'Alles erledigt'}</h3>${approvals||'<div class="su-empty">Keine Kalender-Freigabe wartet auf dich.</div>'}</section></div>
      <section class="su-card su-details"><details ${simple.details?'open':''}><summary>Optionen & Details</summary><div style="margin-top:12px"><label class="su-muted">Kalender&nbsp; <select id="su-calendar" class="su-select">${simple.calendars.map(c=>`<option value="${html(c.id)}" ${String(c.id)===String(simple.calendarId)?'selected':''}>${html(c.summary||c.id)}${c.primary?' · primär':''}</option>`).join('')}</select></label><div class="su-actions" style="margin-top:10px"><button class="su-btn" id="su-refresh">Kalender aktualisieren</button><button class="su-btn" data-su-quick="Welche drei nächsten freien 60-Minuten-Zeiten habe ich während meiner üblichen Arbeitszeit?">3 freie Zeiten finden</button><button class="su-btn" id="su-renew">Google-Berechtigungen erneuern</button></div></div></details></section>
    </div>`;
  }

  async function connectCalendar() {
    const popup = window.open('about:blank', 'mail-agent-google-calendar', 'popup=yes,width=620,height=760');
    if (!popup) return showNotice('Pop-up wurde blockiert. Bitte Pop-ups für MAIL-AGENT erlauben.', 'error');
    try {
      const acct = account();
      const start = await api('/v1/oauth/google/calendar/start', {method:'POST', body:JSON.stringify({login_hint:acct?.email_address||null})});
      popup.location.replace(start.authorization_url);
      const deadline = Date.now() + 5*60*1000;
      while (Date.now() < deadline) {
        await new Promise(resolve=>setTimeout(resolve,700));
        const status = await api(`/v1/oauth/sessions/${encodeURIComponent(start.state)}`).catch(()=>null);
        if (status?.status === 'complete') {
          try { popup.close(); } catch (_) {}
          simple.loaded=false; await loadSimple(true); showNotice('Google Kalender ist verbunden.'); render(); return;
        }
        if (status?.status === 'error') throw new Error(status.error || 'Google-Anmeldung fehlgeschlagen');
      }
      throw new Error('Google-Anmeldung wurde nicht rechtzeitig abgeschlossen.');
    } catch (error) {
      try { popup.close(); } catch (_) {}
      showNotice(error.message,'error');
    }
  }

  async function runAssistant(instruction, sourceMessageId=simple.sourceMessageId) {
    if (!instruction.trim()) return;
    const input=document.getElementById('su-instruction'); if(input)input.disabled=true;
    try {
      simple.result = await api('/v1/calendar/concierge', {method:'POST', body:JSON.stringify({
        mailbox_id:simple.mailboxId,
        instruction:instruction.trim(),
        calendar_id:simple.calendarId,
        source_message_id:sourceMessageId||null,
        duration_minutes:60,
        actor:'local-user',
      })});
      await loadSimple(true);
      render();
    } catch (error) {
      showNotice(error.message,'error');
    } finally { if(input)input.disabled=false; }
  }

  async function decideCalendar(id, decision) {
    try {
      await api(`/v1/calendar/approvals/${encodeURIComponent(id)}/${decision}`, {method:'POST', body:JSON.stringify({actor:'local-user'})});
      await loadSimple(true); showNotice(decision==='approve'?'Kalenderänderung ausgeführt.':'Kalenderänderung abgelehnt.'); render();
    } catch(error){showNotice(error.message,'error');}
  }

  function bindSimple() {
    document.getElementById('su-connect')?.addEventListener('click',connectCalendar);
    document.getElementById('su-renew')?.addEventListener('click',connectCalendar);
    document.getElementById('su-refresh')?.addEventListener('click',async()=>{simple.loaded=false;await loadSimple(true);render();});
    document.getElementById('su-source-clear')?.addEventListener('click',()=>{simple.sourceMessageId='';simple.sourceSubject='';cal.sourceMessageId='';cal.sourceSubject='';render();});
    document.getElementById('su-run')?.addEventListener('click',()=>runAssistant(document.getElementById('su-instruction')?.value||''));
    document.querySelectorAll('[data-su-quick]').forEach(button=>button.addEventListener('click',()=>runAssistant(button.dataset.suQuick,'')));
    document.querySelectorAll('[data-su-mail]').forEach(button=>button.addEventListener('click',()=>{
      const item=simple.suggestions[Number(button.dataset.suMail)]; if(!item)return;
      simple.sourceMessageId=item.message_id; simple.sourceSubject=item.subject||''; cal.sourceMessageId=item.message_id;cal.sourceSubject=item.subject||'';
      runAssistant('Prüfe den in dieser Mail konkret vorgeschlagenen Termin gegen meinen Kalender. Wenn er belegt ist, nenne mir passende Alternativen am selben Tag.',item.message_id);
    }));
    document.getElementById('su-prepare-target')?.addEventListener('click',()=>runAssistant('Erstelle den in dieser Mail genannten Termin als Kalendereintrag. Keine Teilnehmer einladen.',simple.sourceMessageId));
    document.querySelectorAll('[data-su-approve]').forEach(button=>button.addEventListener('click',()=>decideCalendar(button.dataset.suApprove,'approve')));
    document.querySelectorAll('[data-su-reject]').forEach(button=>button.addEventListener('click',()=>decideCalendar(button.dataset.suReject,'reject')));
    document.getElementById('su-calendar')?.addEventListener('change',async event=>{simple.calendarId=event.target.value;cal.calendarId=simple.calendarId;simple.loaded=false;await loadSimple(true);render();});
  }

  const previousRenderDashboard = renderDashboard;
  renderDashboard = function v171RenderDashboard() {
    if (activeView !== 'calendar') return previousRenderDashboard();
    app.innerHTML = dashboardLayout(calendarPage());
    bindDashboard();
    bindSimple();
  };
})();
