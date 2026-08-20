(() => {
  const state = {
    status: null,
    mailboxId: '',
    calendars: [],
    calendarId: 'primary',
    events: [],
    approvals: [],
    editingEventId: '',
    busyText: '',
    loading: false,
  };

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const api = async (url, options={}) => {
    const response = await fetch(url, {cache:'no-store', headers:{'Content-Type':'application/json', ...(options.headers||{})}, ...options});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    return payload;
  };
  const notify = (message, error=false) => {
    if (typeof showNotice === 'function') { showNotice(message, error ? 'error' : 'success'); return; }
    console[error?'error':'log'](message);
  };
  const localInput = value => {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    const pad = n => String(n).padStart(2,'0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const rfc3339 = value => {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) throw new Error('Bitte gültige Start- und Endzeit wählen.');
    return d.toISOString();
  };
  const fmt = value => {
    if (!value) return '—';
    try { return new Date(value).toLocaleString('de-DE', {dateStyle:'medium', timeStyle:'short'}); }
    catch (_) { return value; }
  };
  const eventStart = event => event?.start?.dateTime || event?.start?.date || '';
  const eventEnd = event => event?.end?.dateTime || event?.end?.date || '';

  function ensureStyles() {
    if (document.getElementById('calendar-ui-styles')) return;
    const style = document.createElement('style');
    style.id = 'calendar-ui-styles';
    style.textContent = `
      .cal-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(320px,.9fr);gap:16px;margin-top:18px}
      .cal-card{border:1px solid #25344b;border-radius:18px;background:#0e1827;padding:18px;min-width:0}
      .cal-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}.cal-head h3{margin:0 0 5px;font-size:17px}.cal-head p{margin:0;color:#91a4c2;font-size:13px;line-height:1.45}
      .cal-status{display:inline-flex;align-items:center;gap:7px;border:1px solid #31445f;border-radius:999px;padding:6px 10px;font-size:12px}.cal-status i{width:7px;height:7px;border-radius:50%;background:#72c593}.cal-status.off i{background:#d79a61}
      .cal-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}.cal-field{display:grid;gap:6px}.cal-field.full{grid-column:1/-1}.cal-field span{font-size:12px;color:#91a4c2}.cal-field input,.cal-field select{width:100%;box-sizing:border-box;border:1px solid #2a3b56;background:#091321;color:#edf3ff;border-radius:10px;padding:10px 11px;outline:none}.cal-field input:focus,.cal-field select:focus{border-color:#5e82b7}
      .cal-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.cal-btn{border:1px solid #31445f;background:#132238;color:#eaf2ff;border-radius:10px;padding:9px 12px;cursor:pointer}.cal-btn.primary{background:#e8eef9;color:#0b1220;border-color:#e8eef9;font-weight:700}.cal-btn.danger{border-color:#6d3943;color:#ffbbc4;background:#24141a}.cal-btn:disabled{opacity:.5;cursor:default}
      .cal-list{display:grid;gap:8px;max-height:360px;overflow:auto}.cal-row{border:1px solid #22334c;border-radius:12px;padding:11px;background:#0a1422}.cal-row-top{display:flex;justify-content:space-between;gap:10px}.cal-row b{font-size:13px}.cal-row small{display:block;color:#8ca0bf;margin-top:4px}.cal-row-actions{display:flex;gap:6px;margin-top:8px}.cal-mini{font-size:11px;padding:6px 8px}
      .cal-approval{border-left:3px solid #d9aa65}.cal-empty{color:#8195b4;font-size:13px;padding:12px 2px}.cal-note{font-size:12px;color:#8fa4c5;margin-top:10px;line-height:1.5}.cal-busy{margin-top:10px;border:1px solid #2b405c;border-radius:10px;padding:10px;color:#b9c8de;font-size:12px}.cal-agent{border:1px solid #304663;border-radius:14px;background:#0a1525;padding:13px;margin-bottom:14px}.cal-agent strong{display:block;margin-bottom:5px}.cal-agent small{display:block;color:#8fa4c5;margin-bottom:9px}
      @media(max-width:980px){.cal-grid{grid-template-columns:1fr}.cal-fields{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function account() {
    return (state.status?.accounts || []).find(item => item.mailbox_id === state.mailboxId) || state.status?.accounts?.[0] || null;
  }

  function render() {
    const root = document.getElementById('calendar-settings-root');
    if (!root) return;
    const acct = account();
    const connected = acct?.connected === true;
    const calendars = state.calendars.length ? state.calendars : [{id:'primary',summary:'Primärer Kalender',primary:true}];
    const pending = state.approvals || [];
    root.innerHTML = `
      <section class="cal-card">
        <div class="cal-head"><div><h3>Google Kalender</h3><p>Termine lesen und Verfügbarkeit prüfen. Erstellen, Ändern, Löschen oder Einladen wird niemals direkt ausgeführt, sondern wartet auf deine Freigabe.</p></div><span class="cal-status ${connected?'':'off'}"><i></i>${connected?'Verbunden':'Nicht verbunden'}</span></div>
        <div class="cal-actions">
          <button class="cal-btn primary" id="calendar-connect">${connected?'Berechtigungen erneuern':'Google Kalender verbinden'}</button>
          ${connected?'<button class="cal-btn" id="calendar-refresh">Aktualisieren</button>':''}
        </div>
        ${acct?`<div class="cal-note">Google-Konto: <b>${esc(acct.email_address||'')}</b>${connected?' · Calendar API aktiv':` · fehlende Berechtigungen: ${esc((acct.missing_scopes||[]).map(x=>x.split('/').pop()).join(', '))}`}</div>`:'<div class="cal-note">Der Kalender wird per Google OAuth mit demselben lokalen, verschlüsselten Token-Vault wie Gmail verbunden.</div>'}
      </section>
      ${connected?`<div class="cal-grid">
        <section class="cal-card">
          <div class="cal-agent"><strong>Kalender-Agent</strong><small>Beschreibe dein Ziel in natürlicher Sprache. Der Agent berücksichtigt vorhandene Termine und legt nur einen prüfbaren Vorschlag in die Freigabe-Queue.</small><label class="cal-field"><span>Auftrag</span><input id="calendar-agent-instruction" maxlength="8000" placeholder="z. B. Plane morgen Nachmittag einen freien 60-Minuten-Termin für Projekt X"></label><div class="cal-actions"><button class="cal-btn primary" id="calendar-agent-propose">Agent Vorschlag erstellen</button></div></div>
          <div class="cal-head"><div><h3>Termin manuell vorbereiten</h3><p>Alternativ kannst du die Eckdaten selbst setzen. Auch hier schreibt erst deine Freigabe zu Google.</p></div></div>
          <div class="cal-fields">
            <label class="cal-field full"><span>Kalender</span><select id="calendar-id">${calendars.map(c=>`<option value="${esc(c.id)}" ${String(c.id)===String(state.calendarId)?'selected':''}>${esc(c.summary||c.id)}${c.primary?' · primär':''}</option>`).join('')}</select></label>
            <label class="cal-field full"><span>Titel</span><input id="calendar-title" maxlength="500" placeholder="z. B. Projektbesprechung"></label>
            <label class="cal-field"><span>Start</span><input id="calendar-start" type="datetime-local"></label>
            <label class="cal-field"><span>Ende</span><input id="calendar-end" type="datetime-local"></label>
            <label class="cal-field full"><span>Ort</span><input id="calendar-location" maxlength="1000" placeholder="optional"></label>
            <label class="cal-field full"><span>Teilnehmer</span><input id="calendar-attendees" placeholder="mail@example.de, zweite@example.de"></label>
            <label class="cal-field full"><span><input id="calendar-send-updates" type="checkbox"> Google-Einladungen nach Freigabe versenden</span></label>
          </div>
          <div class="cal-actions"><button class="cal-btn" id="calendar-freebusy">Zeitraum auf Belegung prüfen</button><button class="cal-btn primary" id="calendar-propose">${state.editingEventId?'Änderung zur Freigabe':'Termin zur Freigabe'}</button>${state.editingEventId?'<button class="cal-btn" id="calendar-edit-cancel">Bearbeiten abbrechen</button>':''}</div>
          <div id="calendar-busy-result" class="cal-busy" style="${state.busyText?'':'display:none'}">${esc(state.busyText)}</div>
          <div class="cal-note">Sicherheitsgrenze: Calendar-Mutationen haben immer <b>requires_approval=true</b>. Auch im autonomen Modus gibt es keinen direkten Schreibpfad.</div>
        </section>
        <section class="cal-card">
          <div class="cal-head"><div><h3>Nächste Termine</h3><p>Bis zu 30 Tage aus dem gewählten Kalender.</p></div></div>
          <div class="cal-list">${state.events.length?state.events.map(event=>`<div class="cal-row"><div class="cal-row-top"><b>${esc(event.summary||'(ohne Titel)')}</b><span>${esc(fmt(eventStart(event)))}</span></div><small>${esc(event.location||'')}${event.location?' · ':''}${esc(fmt(eventEnd(event)))}</small><div class="cal-row-actions"><button class="cal-btn cal-mini" data-calendar-edit="${esc(event.id)}">Ändern</button><button class="cal-btn cal-mini danger" data-calendar-delete="${esc(event.id)}">Löschen vorschlagen</button></div></div>`).join(''):'<div class="cal-empty">Keine Termine im gewählten Zeitraum.</div>'}</div>
        </section>
        <section class="cal-card" style="grid-column:1/-1">
          <div class="cal-head"><div><h3>Kalender-Freigaben</h3><p>${pending.length} Aktion${pending.length===1?'':'en'} wartet${pending.length===1?'':'en'} auf eine menschliche Entscheidung.</p></div></div>
          <div class="cal-list">${pending.length?pending.map(item=>{const p=item.proposal||{};const ev=p.event||{};return `<div class="cal-row cal-approval"><div class="cal-row-top"><b>${esc({create:'Termin erstellen',update:'Termin ändern',delete:'Termin löschen'}[p.action]||p.action)}</b><span>High risk</span></div><small>${esc(ev.summary||p.event_id||'Kalender-Aktion')} ${ev.start?`· ${esc(fmt(ev.start))}`:''}</small><div class="cal-row-actions"><button class="cal-btn cal-mini danger" data-calendar-reject="${esc(item.approval_id)}">Ablehnen</button><button class="cal-btn cal-mini primary" data-calendar-approve="${esc(item.approval_id)}">Freigeben & ausführen</button></div></div>`}).join(''):'<div class="cal-empty">Keine Kalender-Aktion wartet auf Freigabe.</div>'}</div>
        </section>
      </div>`:''}
    `;
    bind(root);
  }

  async function loadCalendarData() {
    const acct = account();
    if (!acct?.connected) { state.calendars=[]; state.events=[]; state.approvals=[]; render(); return; }
    state.mailboxId = state.mailboxId || acct.mailbox_id;
    const calendars = await api(`/v1/calendar/calendars?mailbox_id=${encodeURIComponent(state.mailboxId)}`);
    state.calendars = calendars.calendars || [];
    if (!state.calendars.some(c=>String(c.id)===String(state.calendarId))) {
      state.calendarId = state.calendars.find(c=>c.primary)?.id || state.calendars[0]?.id || 'primary';
    }
    const [events, approvals] = await Promise.all([
      api(`/v1/calendar/events?mailbox_id=${encodeURIComponent(state.mailboxId)}&calendar_id=${encodeURIComponent(state.calendarId)}&max_results=100`),
      api('/v1/calendar/approvals?status=pending&limit=100'),
    ]);
    state.events = events.events || [];
    state.approvals = approvals.approvals || [];
    render();
  }

  async function refresh() {
    if (state.loading) return;
    state.loading = true;
    try {
      state.status = await api('/v1/calendar/status');
      const firstConnected = (state.status.accounts||[]).find(x=>x.connected) || state.status.accounts?.[0];
      if (firstConnected && !state.mailboxId) state.mailboxId = firstConnected.mailbox_id;
      await loadCalendarData();
    } catch (error) {
      notify(error.message, true);
      render();
    } finally { state.loading = false; }
  }

  async function connect() {
    try {
      const acct = account();
      const result = await api('/v1/oauth/google/calendar/start', {method:'POST', body:JSON.stringify({login_hint:acct?.email_address||null})});
      const popup = window.open(result.authorization_url, 'mail-agent-google-calendar', 'width=620,height=760');
      if (!popup) throw new Error('Popup wurde blockiert. Bitte Popups für MAIL-AGENT erlauben.');
      const deadline = Date.now() + 120000;
      const poll = async () => {
        if (Date.now() > deadline) return notify('Google-Kalender-Verbindung hat das Zeitlimit erreicht.', true);
        try {
          const session = await api(`/v1/oauth/sessions/${encodeURIComponent(result.state)}`);
          if (session.status === 'complete') { try { popup.close(); } catch(_){} notify('Google Kalender verbunden.'); state.status=null; await refresh(); return; }
          if (session.status === 'error') { try { popup.close(); } catch(_){} notify(session.error||'Google Kalender konnte nicht verbunden werden.', true); return; }
        } catch (_) {}
        window.setTimeout(poll, 900);
      };
      window.setTimeout(poll, 900);
    } catch (error) { notify(error.message, true); }
  }

  function formValue(id) { return document.getElementById(id)?.value || ''; }

  async function askAgent() {
    const instruction = formValue('calendar-agent-instruction').trim();
    if (!instruction) throw new Error('Bitte beschreibe, was der Kalender-Agent vorbereiten soll.');
    await api('/v1/calendar/assist', {
      method:'POST',
      body:JSON.stringify({mailbox_id:state.mailboxId, calendar_id:state.calendarId, instruction, actor:'local-user'}),
    });
    notify('Der Kalender-Agent hat einen Vorschlag erstellt. Bitte prüfe die Freigabe.');
    await loadCalendarData();
  }

  async function propose(action, eventId='') {
    let event = null;
    if (action !== 'delete') {
      const title = formValue('calendar-title').trim();
      if (!title) throw new Error('Bitte einen Termintitel eingeben.');
      event = {
        summary:title,
        start:rfc3339(formValue('calendar-start')),
        end:rfc3339(formValue('calendar-end')),
        location:formValue('calendar-location').trim() || null,
        attendees:formValue('calendar-attendees').split(',').map(x=>x.trim()).filter(Boolean),
      };
    }
    const proposal = {
      action,
      mailbox_id:state.mailboxId,
      calendar_id:state.calendarId,
      event_id:eventId || null,
      event,
      send_updates:document.getElementById('calendar-send-updates')?.checked ? 'all' : 'none',
      reason:'Vom Benutzer in der Kalenderoberfläche vorbereitet.',
    };
    await api('/v1/calendar/proposals', {method:'POST', body:JSON.stringify({proposal,actor:'local-user'})});
    state.editingEventId='';
    notify('Kalender-Aktion wartet jetzt auf deine Freigabe.');
    await loadCalendarData();
  }

  async function checkBusy() {
    const start = rfc3339(formValue('calendar-start'));
    const end = rfc3339(formValue('calendar-end'));
    const result = await api('/v1/calendar/freebusy', {method:'POST', body:JSON.stringify({mailbox_id:state.mailboxId,time_min:start,time_max:end,calendar_ids:[state.calendarId]})});
    const busy = result.calendars?.[state.calendarId]?.busy || [];
    state.busyText = busy.length ? `Belegt: ${busy.map(x=>`${fmt(x.start)} – ${fmt(x.end)}`).join(' · ')}` : 'Der gewählte Zeitraum ist laut Google Kalender frei.';
    const box = document.getElementById('calendar-busy-result');
    if (box) { box.textContent = state.busyText; box.style.display = ''; }
  }

  function startEdit(eventId) {
    const event = state.events.find(item=>String(item.id)===String(eventId));
    if (!event) return;
    state.editingEventId = event.id;
    state.busyText = '';
    render();
    const set = (id,value) => { const el=document.getElementById(id); if(el) el.value=value||''; };
    set('calendar-title', event.summary||'');
    set('calendar-start', localInput(eventStart(event)));
    set('calendar-end', localInput(eventEnd(event)));
    set('calendar-location', event.location||'');
    set('calendar-attendees', (event.attendees||[]).map(x=>x.email).filter(Boolean).join(', '));
  }

  function bind(root) {
    root.querySelector('#calendar-connect')?.addEventListener('click', connect);
    root.querySelector('#calendar-refresh')?.addEventListener('click', refresh);
    root.querySelector('#calendar-id')?.addEventListener('change', async e => { state.calendarId=e.target.value; state.busyText=''; await loadCalendarData(); });
    root.querySelector('#calendar-agent-propose')?.addEventListener('click', () => askAgent().catch(e=>notify(e.message,true)));
    root.querySelector('#calendar-freebusy')?.addEventListener('click', () => checkBusy().catch(e=>notify(e.message,true)));
    root.querySelector('#calendar-propose')?.addEventListener('click', () => propose(state.editingEventId?'update':'create', state.editingEventId).catch(e=>notify(e.message,true)));
    root.querySelector('#calendar-edit-cancel')?.addEventListener('click', () => { state.editingEventId=''; state.busyText=''; render(); });
    root.querySelectorAll('[data-calendar-edit]').forEach(btn=>btn.addEventListener('click',()=>startEdit(btn.dataset.calendarEdit)));
    root.querySelectorAll('[data-calendar-delete]').forEach(btn=>btn.addEventListener('click',async()=>{try{await propose('delete',btn.dataset.calendarDelete);}catch(e){notify(e.message,true)}}));
    root.querySelectorAll('[data-calendar-approve]').forEach(btn=>btn.addEventListener('click',async()=>{try{await api(`/v1/calendar/approvals/${encodeURIComponent(btn.dataset.calendarApprove)}/approve`,{method:'POST',body:JSON.stringify({actor:'local-user'})});notify('Kalender-Aktion ausgeführt.');await loadCalendarData();}catch(e){notify(e.message,true)}}));
    root.querySelectorAll('[data-calendar-reject]').forEach(btn=>btn.addEventListener('click',async()=>{try{await api(`/v1/calendar/approvals/${encodeURIComponent(btn.dataset.calendarReject)}/reject`,{method:'POST',body:JSON.stringify({actor:'local-user'})});notify('Kalender-Aktion abgelehnt.');await loadCalendarData();}catch(e){notify(e.message,true)}}));
  }

  function mount() {
    const settingsMarker = document.getElementById('settings-save-llm') || document.getElementById('settings-save-profile');
    if (!settingsMarker) return false;
    const content = document.querySelector('.wb-content') || settingsMarker.closest('main') || settingsMarker.parentElement;
    if (!content) return false;
    ensureStyles();
    let root = document.getElementById('calendar-settings-root');
    if (!root) {
      root = document.createElement('section');
      root.id = 'calendar-settings-root';
      root.style.marginTop = '18px';
      content.appendChild(root);
    }
    render();
    refresh();
    return true;
  }

  document.addEventListener('click', event => {
    if (event.target.closest?.('[data-view="settings"]')) window.setTimeout(mount, 80);
  });
  window.setTimeout(mount, 400);
})();
