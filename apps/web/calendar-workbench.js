(() => {
  const cal = {
    status: null,
    mailboxId: '',
    calendars: [],
    calendarId: 'primary',
    briefing: null,
    events: [],
    approvals: [],
    failed: [],
    freeSlots: [],
    answer: '',
    answerKind: '',
    sourceMessageId: '',
    sourceSubject: '',
    loading: false,
  };

  const html = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));
  const fmt = value => {
    if (!value) return '—';
    try { return new Date(value).toLocaleString('de-DE', {dateStyle:'medium', timeStyle:'short'}); }
    catch (_) { return String(value); }
  };
  const eventStart = event => event?.start?.dateTime || event?.start?.date || '';
  const eventEnd = event => event?.end?.dateTime || event?.end?.date || '';
  const sourceId = item => String(item?.remote_id || item?.internet_message_id || item?.uid || '');
  const account = () => (cal.status?.accounts || []).find(x => x.mailbox_id === cal.mailboxId)
    || (cal.status?.accounts || []).find(x => x.connected)
    || cal.status?.accounts?.[0]
    || null;

  async function api(path, options={}) {
    const response = await fetch(path, {
      cache:'no-store',
      headers:{'Content-Type':'application/json', ...(options.headers||{})},
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string'
        ? payload.detail
        : payload.detail?.message || JSON.stringify(payload.detail || {});
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  function notify(message, error=false) {
    if (typeof showNotice === 'function') showNotice(message, error ? 'error' : 'success');
  }

  function ensureStyles() {
    if (document.getElementById('calendar-workbench-styles')) return;
    const style = document.createElement('style');
    style.id = 'calendar-workbench-styles';
    style.textContent = `
      .cw-shell{display:grid;gap:14px}.cw-hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;border:1px solid #25344b;border-radius:18px;background:#0e1827;padding:20px}.cw-hero h2{margin:3px 0 7px;font-size:24px}.cw-hero p{margin:0;color:#91a4c2;max-width:760px;line-height:1.5}.cw-kicker{font-size:11px;letter-spacing:.12em;color:#7790b4}.cw-status{border:1px solid #31445f;border-radius:999px;padding:7px 11px;font-size:12px;white-space:nowrap}.cw-status.ok{color:#9eddb6}.cw-status.off{color:#e7b77f}
      .cw-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:14px}.cw-card{border:1px solid #25344b;border-radius:16px;background:#0d1725;padding:17px;min-width:0}.cw-card.full{grid-column:1/-1}.cw-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}.cw-head h3{margin:0 0 4px;font-size:16px}.cw-head p{margin:0;color:#879bbc;font-size:12px;line-height:1.45}.cw-actions{display:flex;gap:8px;flex-wrap:wrap}.cw-btn{border:1px solid #324762;background:#132238;color:#eaf2ff;border-radius:9px;padding:8px 11px;cursor:pointer}.cw-btn.primary{background:#e9eef7;border-color:#e9eef7;color:#0a1220;font-weight:700}.cw-btn.danger{background:#241419;border-color:#6d3943;color:#ffc0c8}.cw-btn:disabled{opacity:.5}.cw-row{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #1d2c42;padding:11px 0}.cw-row:first-child{border-top:0}.cw-row b{display:block;font-size:13px}.cw-row small{display:block;color:#8398b8;margin-top:4px;line-height:1.4}.cw-right{text-align:right;flex:0 0 auto}.cw-tag{display:inline-flex;border:1px solid #31445f;border-radius:999px;padding:4px 7px;font-size:10px;color:#a9bbd4}.cw-input,.cw-select,.cw-textarea{width:100%;box-sizing:border-box;border:1px solid #2a3b56;background:#081321;color:#edf3ff;border-radius:10px;padding:10px 11px;outline:none}.cw-textarea{min-height:92px;resize:vertical}.cw-fields{display:grid;grid-template-columns:1fr 1fr;gap:9px}.cw-field{display:grid;gap:5px}.cw-field.full{grid-column:1/-1}.cw-field span{font-size:11px;color:#8da1be}.cw-result{margin-top:11px;border:1px solid #2c425f;border-radius:11px;padding:11px;color:#c2d0e4;line-height:1.5;font-size:13px}.cw-result.clarification{border-color:#765a35}.cw-result.proposal{border-color:#3f6b55}.cw-slots{display:flex;gap:7px;flex-wrap:wrap}.cw-slot{border:1px solid #2c425f;border-radius:10px;padding:8px 9px;background:#091522;font-size:11px}.cw-source{margin:9px 0;border:1px solid #49617e;border-radius:11px;padding:10px;background:#0b192a;font-size:12px}.cw-source b{display:block;margin-bottom:3px}.cw-empty{color:#8397b5;padding:10px 0;font-size:13px}.cw-warning{border:1px solid #674c2f;background:#21190f;border-radius:11px;padding:10px;color:#e7c99d;font-size:12px;line-height:1.45}.cw-approval{border-left:3px solid #d4a45e;padding-left:10px}.cw-mail-buttons{display:flex;gap:7px;flex-wrap:wrap;margin-right:auto}
      @media(max-width:980px){.cw-grid{grid-template-columns:1fr}.cw-card.full{grid-column:auto}.cw-fields{grid-template-columns:1fr}.cw-hero{display:grid}}
    `;
    document.head.appendChild(style);
  }

  async function loadCalendar(force=false) {
    if (cal.loading && !force) return;
    cal.loading = true;
    try {
      cal.status = await api('/v1/calendar/status');
      const selected = account();
      if (!cal.mailboxId && selected) cal.mailboxId = selected.mailbox_id;
      if (!selected?.connected) {
        cal.calendars=[]; cal.briefing=null; cal.events=[]; cal.approvals=[]; cal.failed=[];
        return;
      }
      const calendars = await api(`/v1/calendar/calendars?mailbox_id=${encodeURIComponent(cal.mailboxId)}`);
      cal.calendars = calendars.calendars || [];
      if (!cal.calendars.some(x => String(x.id) === String(cal.calendarId))) {
        cal.calendarId = cal.calendars.find(x => x.primary)?.id || cal.calendars[0]?.id || 'primary';
      }
      const [briefing, events, pending, approved] = await Promise.all([
        api(`/v1/calendar/briefing?mailbox_id=${encodeURIComponent(cal.mailboxId)}&calendar_id=${encodeURIComponent(cal.calendarId)}&duration_minutes=60`),
        api(`/v1/calendar/events?mailbox_id=${encodeURIComponent(cal.mailboxId)}&calendar_id=${encodeURIComponent(cal.calendarId)}&max_results=100`),
        api('/v1/calendar/approvals?status=pending&limit=100'),
        api('/v1/calendar/approvals?status=approved&limit=100'),
      ]);
      cal.briefing = briefing;
      cal.events = events.events || [];
      cal.approvals = pending.approvals || [];
      cal.failed = (approved.approvals || []).filter(x => ['failed','ready'].includes(x.execution_status));
      if (!cal.freeSlots.length) cal.freeSlots = briefing.next_free_slots || [];
    } finally {
      cal.loading = false;
    }
  }

  function connectButton() {
    const acct = account();
    const supported = cal.status?.supported !== false;
    return `<button class="cw-btn primary" id="cw-connect" ${supported?'':'disabled'}>${acct?.connected?'Berechtigungen erneuern':'Google Kalender verbinden'}</button>`;
  }

  function calendarPage() {
    ensureStyles();
    const acct = account();
    const connected = acct?.connected === true;
    if (!cal.status) {
      window.setTimeout(() => refreshPage(), 0);
      return '<div class="cw-shell"><section class="cw-card"><div class="cw-empty">Kalender wird geladen …</div></section></div>';
    }
    if (!connected) {
      return `<div class="cw-shell"><section class="cw-hero"><div><span class="cw-kicker">GOOGLE CALENDAR · 0.17</span><h2>Termine nicht nur sehen – Arbeit daraus abnehmen.</h2><p>MAIL-AGENT kann freie Zeiten finden, Terminwünsche aus Mails einordnen, Antworten mit echter Verfügbarkeit vorbereiten und Kalenderänderungen zur Freigabe vorlegen.</p></div><span class="cw-status off">Nicht verbunden</span></section><section class="cw-card"><div class="cw-head"><div><h3>Google Kalender verbinden</h3><p>Der bestehende Google-Login wird um eng begrenzte Calendar-Rechte erweitert. Tokens bleiben im lokalen verschlüsselten Vault.</p></div></div><div class="cw-actions">${connectButton()}</div>${acct?`<div class="cw-warning" style="margin-top:12px">${html(acct.email_address||'Google-Konto')} · fehlende Berechtigungen: ${html((acct.missing_scopes||[]).map(x=>x.split('/').pop()).join(', '))}</div>`:''}</section></div>`;
    }

    const briefing = cal.briefing || {};
    const next = briefing.next_event;
    const today = briefing.today_events || [];
    const calendars = cal.calendars || [];
    const source = cal.sourceMessageId
      ? `<div class="cw-source"><b>Mail-Kontext aktiv</b>${html(cal.sourceSubject||cal.sourceMessageId)}<br><span>Mailtext bleibt untrusted; er kann keine Einladung, Policy oder Kalenderänderung autorisieren.</span><div class="cw-actions" style="margin-top:7px"><button class="cw-btn" id="cw-source-clear">Kontext entfernen</button><button class="cw-btn primary" id="cw-mail-reply">Freie Zeiten als Antwortentwurf</button></div></div>`
      : '';
    return `<div class="cw-shell">
      <section class="cw-hero"><div><span class="cw-kicker">KALENDER · ${html(briefing.time_zone||'')}</span><h2>${today.length?`${today.length} Termin${today.length===1?'':'e'} heute.`:'Heute ist dein Kalender frei.'}</h2><p>${next?`Als Nächstes: ${html(next.summary||'(ohne Titel)')} · ${html(fmt(eventStart(next)))}.`:'Kein weiterer Termin heute.'} Änderungen, Absagen und Einladungen bleiben immer freigabepflichtig.</p></div><div><span class="cw-status ok">Google verbunden</span><div class="cw-actions" style="margin-top:9px">${connectButton()}<button class="cw-btn" id="cw-refresh">Aktualisieren</button></div></div></section>
      <section class="cw-card full"><div class="cw-head"><div><h3>Kalender-Agent</h3><p>Fragen, planen, verschieben oder absagen. Bei fehlenden Angaben fragt der Agent nach, statt etwas zu erfinden.</p></div></div>${source}<textarea class="cw-textarea" id="cw-instruction" placeholder="z. B. Wann habe ich morgen 60 Minuten frei? · Plane nächste Woche einen Termin für Projekt X · Verschiebe meinen Zahnarzttermin auf einen freien Nachmittag"></textarea><div class="cw-fields" style="margin-top:9px"><label class="cw-field"><span>Dauer für neue Termine</span><select class="cw-select" id="cw-duration"><option value="30">30 Minuten</option><option value="45">45 Minuten</option><option value="60" selected>60 Minuten</option><option value="90">90 Minuten</option><option value="120">120 Minuten</option></select></label><label class="cw-field"><span>Kalender</span><select class="cw-select" id="cw-calendar">${calendars.map(c=>`<option value="${html(c.id)}" ${String(c.id)===String(cal.calendarId)?'selected':''}>${html(c.summary||c.id)}${c.primary?' · primär':''}${['owner','writer'].includes(String(c.access_role||'').toLowerCase())?'':' · nur lesen'}</option>`).join('')}</select></label></div><div class="cw-actions" style="margin-top:10px"><button class="cw-btn" data-cw-quick="Was steht heute noch in meinem Kalender?">Heute</button><button class="cw-btn" data-cw-quick="Wann habe ich morgen einen freien Zeitraum für einen 60-Minuten-Termin?">Morgen frei?</button><button class="cw-btn" data-cw-quick="Welche drei nächsten freien 60-Minuten-Zeiten habe ich während meiner Arbeitszeit?">3 freie Zeiten</button><button class="cw-btn primary" id="cw-ask">Agent fragen / vorbereiten</button></div>${cal.answer?`<div class="cw-result ${html(cal.answerKind)}"><b>${cal.answerKind==='proposal'?'Vorschlag wartet auf Freigabe':cal.answerKind==='clarification'?'Rückfrage / Konflikt':'Antwort'}</b><br>${html(cal.answer)}</div>`:''}</section>
      <div class="cw-grid">
        <section class="cw-card"><div class="cw-head"><div><h3>Freie Zeiten</h3><p>Deterministisch aus Google Free/Busy – nicht vom Modell geschätzt.</p></div><button class="cw-btn" id="cw-find-slots">Neu suchen</button></div><div class="cw-fields"><label class="cw-field"><span>Dauer</span><select class="cw-select" id="cw-slot-duration"><option value="30">30 Min</option><option value="60" selected>60 Min</option><option value="90">90 Min</option><option value="120">120 Min</option></select></label><label class="cw-field"><span>Zeitraum</span><select class="cw-select" id="cw-slot-days"><option value="3">3 Tage</option><option value="7" selected>7 Tage</option><option value="14">14 Tage</option><option value="30">30 Tage</option></select></label></div><div class="cw-slots" style="margin-top:11px">${cal.freeSlots.length?cal.freeSlots.map(s=>`<button class="cw-slot" data-cw-slot="${html(s.start)}|${html(s.end)}">${html(fmt(s.start))}<br>${html(s.duration_minutes)} Min</button>`).join(''):'<span class="cw-empty">Keine freien Slots geladen.</span>'}</div></section>
        <section class="cw-card"><div class="cw-head"><div><h3>Heute</h3><p>${html(briefing.calendar_name||'Kalender')}</p></div><span class="cw-tag">${today.length} Termin${today.length===1?'':'e'}</span></div>${today.length?today.map(e=>`<div class="cw-row"><div><b>${html(e.summary||'(ohne Titel)')}</b><small>${html(e.location||'')}${e.location?' · ':''}${html(fmt(eventStart(e)))} – ${html(fmt(eventEnd(e)))}</small></div></div>`).join(''):'<div class="cw-empty">Keine Termine heute.</div>'}</section>
        <section class="cw-card full"><div class="cw-head"><div><h3>Nächste Termine</h3><p>Änderungen werden als Proposal vorbereitet; es gibt keinen Direct-Write-Pfad.</p></div></div>${cal.events.length?cal.events.slice(0,30).map(e=>`<div class="cw-row"><div><b>${html(e.summary||'(ohne Titel)')}</b><small>${html(fmt(eventStart(e)))} – ${html(fmt(eventEnd(e)))}${e.location?` · ${html(e.location)}`:''}</small></div><div class="cw-right"><span class="cw-tag">${html((e.attendees||[]).length)} Teilnehmer</span><div class="cw-actions" style="margin-top:6px"><button class="cw-btn" data-cw-move="${html(e.id)}" data-cw-title="${html(e.summary||'Termin')}">Mit Agent verschieben</button><button class="cw-btn danger" data-cw-delete="${html(e.id)}">Löschen vorschlagen</button></div></div></div>`).join(''):'<div class="cw-empty">Keine kommenden Termine.</div>'}</section>
        <section class="cw-card full"><div class="cw-head"><div><h3>Kalender-Freigaben</h3><p>Erstellen, Ändern, Löschen und externe Einladungen werden hier sichtbar entschieden.</p></div><span class="cw-tag">${cal.approvals.length} offen</span></div>${cal.approvals.length?cal.approvals.map(a=>approvalRow(a,false)).join(''):'<div class="cw-empty">Keine Kalender-Aktion wartet auf dich.</div>'}${cal.failed.length?`<div class="cw-warning" style="margin-top:10px">${cal.failed.length} fehlgeschlagene oder unterbrochene Ausführung${cal.failed.length===1?'':'en'} kann/können sicher erneut geprüft werden.</div>${cal.failed.map(a=>approvalRow(a,true)).join('')}`:''}</section>
      </div>
    </div>`;
  }

  function approvalRow(item, retry) {
    const p = item.proposal || {};
    const ev = p.event || {};
    return `<div class="cw-row cw-approval"><div><b>${html({create:'Termin erstellen',update:'Termin ändern',delete:'Termin löschen'}[p.action]||p.action)}</b><small>${html(ev.summary||p.event_id||'Kalender-Aktion')}${ev.start?` · ${html(fmt(ev.start))}`:''}${p.send_updates==='all'?' · Google-Einladungen werden versendet':''}</small>${item.execution_error?`<small>${html(item.execution_error)}</small>`:''}</div><div class="cw-actions">${retry?`<button class="cw-btn primary" data-cw-retry="${html(item.approval_id)}">Sicher erneut ausführen</button>`:`<button class="cw-btn danger" data-cw-reject="${html(item.approval_id)}">Ablehnen</button><button class="cw-btn primary" data-cw-approve="${html(item.approval_id)}">Freigeben & ausführen</button>`}</div></div>`;
  }

  async function refreshPage() {
    try { await loadCalendar(true); if (activeView === 'calendar') render(); }
    catch (error) { notify(error.message, true); }
  }

  async function connectCalendar() {
    const popup = window.open('about:blank', 'mail-agent-google-calendar', 'popup=yes,width=620,height=760');
    if (!popup) { notify('Pop-up wurde blockiert. Bitte Pop-ups für MAIL-AGENT erlauben.', true); return; }
    try {
      const acct = account();
      const start = await api('/v1/oauth/google/calendar/start', {
        method:'POST', body:JSON.stringify({login_hint:acct?.email_address||null}),
      });
      popup.location.replace(start.authorization_url);
      const deadline = Date.now() + 5 * 60 * 1000;
      while (Date.now() < deadline) {
        const session = await api(`/v1/oauth/sessions/${encodeURIComponent(start.state)}`);
        if (session.status === 'complete') {
          try { popup.close(); } catch (_) {}
          cal.status = null;
          await loadCalendar(true);
          notify('Google Kalender ist verbunden.');
          if (activeView === 'calendar') render();
          return;
        }
        if (session.status === 'error') throw new Error(session.error || 'Google Kalender konnte nicht verbunden werden.');
        await new Promise(resolve => window.setTimeout(resolve, 700));
      }
      throw new Error('Google-Kalender-Anmeldung hat zu lange gedauert.');
    } catch (error) {
      try { popup.close(); } catch (_) {}
      notify(error.message, true);
    }
  }

  async function askCalendar() {
    const instruction = document.getElementById('cw-instruction')?.value?.trim() || '';
    if (!instruction) throw new Error('Bitte beschreibe, wobei der Kalender-Agent helfen soll.');
    const duration = Number(document.getElementById('cw-duration')?.value || 60);
    const result = await api('/v1/calendar/concierge', {
      method:'POST',
      body:JSON.stringify({
        mailbox_id:cal.mailboxId,
        calendar_id:cal.calendarId,
        instruction,
        source_message_id:cal.sourceMessageId || null,
        duration_minutes:duration,
        window_days:30,
        actor:'local-user',
        allow_notifications:false,
        allow_conflict:false,
      }),
    });
    cal.answerKind = result.kind || 'answer';
    cal.answer = result.answer || (result.kind === 'proposal' ? 'Vorschlag erstellt.' : '');
    if (result.free_slots?.length) cal.freeSlots = result.free_slots;
    await loadCalendar(true);
    render();
  }

  async function findSlots() {
    const duration = Number(document.getElementById('cw-slot-duration')?.value || 60);
    const days = Number(document.getElementById('cw-slot-days')?.value || 7);
    const now = new Date();
    const end = new Date(now.getTime() + days * 86400000);
    const result = await api('/v1/calendar/free-slots', {
      method:'POST',
      body:JSON.stringify({
        mailbox_id:cal.mailboxId,
        calendar_ids:[cal.calendarId],
        time_min:now.toISOString(),
        time_max:end.toISOString(),
        duration_minutes:duration,
        max_results:12,
      }),
    });
    cal.freeSlots = result.slots || [];
    render();
  }

  async function deleteProposal(eventId) {
    await api('/v1/calendar/proposals', {
      method:'POST',
      body:JSON.stringify({
        actor:'local-user',
        proposal:{
          action:'delete', mailbox_id:cal.mailboxId, calendar_id:cal.calendarId,
          event_id:eventId, send_updates:'none', reason:'Vom Benutzer im Kalender-Arbeitsbereich angefordert.',
        },
      }),
    });
    notify('Löschen wartet auf deine Freigabe.');
    await loadCalendar(true); render();
  }

  async function availabilityReply() {
    if (!cal.sourceMessageId) throw new Error('Keine Mail als Termin-Kontext ausgewählt.');
    const result = await api('/v1/calendar/mail-reply', {
      method:'POST',
      body:JSON.stringify({
        mailbox_id:cal.mailboxId,
        source_message_id:cal.sourceMessageId,
        calendar_id:cal.calendarId,
        duration_minutes:60,
        slot_count:3,
        actor:'local-user',
      }),
    });
    await loadDashboard(true);
    activeView = 'drafts';
    notify(`${result.free_slots?.length||0} echte freie Zeiten wurden als signierter Antwortentwurf vorbereitet.`);
    render();
  }

  function bindCalendar() {
    document.getElementById('cw-connect')?.addEventListener('click', connectCalendar);
    document.getElementById('cw-refresh')?.addEventListener('click', refreshPage);
    document.getElementById('cw-calendar')?.addEventListener('change', async event => {
      cal.calendarId = event.target.value; cal.freeSlots=[]; await refreshPage();
    });
    document.getElementById('cw-ask')?.addEventListener('click', () => askCalendar().catch(e=>notify(e.message,true)));
    document.getElementById('cw-find-slots')?.addEventListener('click', () => findSlots().catch(e=>notify(e.message,true)));
    document.getElementById('cw-source-clear')?.addEventListener('click', () => { cal.sourceMessageId='';cal.sourceSubject='';render(); });
    document.getElementById('cw-mail-reply')?.addEventListener('click', () => availabilityReply().catch(e=>notify(e.message,true)));
    document.querySelectorAll('[data-cw-quick]').forEach(button => button.addEventListener('click', () => {
      const input=document.getElementById('cw-instruction'); if(input){input.value=button.dataset.cwQuick;input.focus();}
    }));
    document.querySelectorAll('[data-cw-slot]').forEach(button => button.addEventListener('click', () => {
      const [start,end]=button.dataset.cwSlot.split('|');
      const input=document.getElementById('cw-instruction');
      if(input){input.value=`Plane einen Termin im freien Zeitraum ${fmt(start)} bis ${fmt(end)}.`;input.focus();}
    }));
    document.querySelectorAll('[data-cw-move]').forEach(button => button.addEventListener('click', () => {
      const input=document.getElementById('cw-instruction');
      if(input){input.value=`Verschiebe den Termin „${button.dataset.cwTitle}“ (Event-ID ${button.dataset.cwMove}) auf einen passenden freien Zeitpunkt. Falls das Ziel nicht eindeutig ist, frage mich nach dem gewünschten Zeitraum.`;input.focus();window.scrollTo({top:0,behavior:'smooth'});}
    }));
    document.querySelectorAll('[data-cw-delete]').forEach(button => button.addEventListener('click', () => deleteProposal(button.dataset.cwDelete).catch(e=>notify(e.message,true))));
    document.querySelectorAll('[data-cw-approve]').forEach(button => button.addEventListener('click', async () => {
      try { await api(`/v1/calendar/approvals/${encodeURIComponent(button.dataset.cwApprove)}/approve`, {method:'POST',body:JSON.stringify({actor:'local-user'})});notify('Kalender-Aktion ausgeführt.');await refreshPage(); }
      catch(e){notify(e.message,true);await refreshPage();}
    }));
    document.querySelectorAll('[data-cw-reject]').forEach(button => button.addEventListener('click', async () => {
      try { await api(`/v1/calendar/approvals/${encodeURIComponent(button.dataset.cwReject)}/reject`, {method:'POST',body:JSON.stringify({actor:'local-user'})});notify('Kalender-Aktion abgelehnt.');await refreshPage(); }
      catch(e){notify(e.message,true);}
    }));
    document.querySelectorAll('[data-cw-retry]').forEach(button => button.addEventListener('click', async () => {
      try { await api(`/v1/calendar/approvals/${encodeURIComponent(button.dataset.cwRetry)}/execute`, {method:'POST',body:'{}'});notify('Kalender-Aktion sicher erneut ausgeführt.');await refreshPage(); }
      catch(e){notify(e.message,true);await refreshPage();}
    }));
  }

  function injectMailBridge() {
    if (!['inbox','attention'].includes(activeView)) return;
    const wb = window.__mailAgentWorkbench;
    const item = activeView === 'inbox'
      ? (dashboard.messages || [])[wb?.selectedMessage || 0]
      : (wb?.attention || [])[wb?.selectedAttention || 0];
    if (!item) return;
    const id = sourceId(item);
    if (!id) return;
    const footer = document.querySelector('.wb-detail-footer');
    if (!footer || footer.querySelector('[data-calendar-from-mail]')) return;
    const group = document.createElement('div');
    group.className = 'cw-mail-buttons';
    group.innerHTML = `<button class="wb-btn" data-calendar-from-mail>Mit Kalender planen</button><button class="wb-btn" data-calendar-reply>Freie Zeiten antworten</button>`;
    footer.prepend(group);
    group.querySelector('[data-calendar-from-mail]')?.addEventListener('click', () => {
      cal.sourceMessageId=id;cal.sourceSubject=item.subject||'';activeView='calendar';render();
    });
    group.querySelector('[data-calendar-reply]')?.addEventListener('click', () => {
      cal.sourceMessageId=id;cal.sourceSubject=item.subject||'';availabilityReply().catch(e=>notify(e.message,true));
    });
  }

  ensureStyles();
  const originalViewTitle = viewTitle;
  const originalDashboardLayout = dashboardLayout;
  const originalRenderDashboard = renderDashboard;

  viewTitle = function calendarViewTitle() {
    return activeView === 'calendar' ? 'Kalender' : originalViewTitle();
  };

  dashboardLayout = function calendarDashboardLayout(content) {
    let markup = originalDashboardLayout(content);
    const controlMarker = '<div class="wb-nav-group"><div class="wb-nav-caption">Steuerung</div>';
    const calendarNav = `<div class="wb-nav-group"><div class="wb-nav-caption">Planung</div><button class="wb-nav-link ${activeView==='calendar'?'active':''}" data-view="calendar">${icon('spark',16)}<span>Kalender</span></button></div>`;
    if (markup.includes(controlMarker)) markup = markup.replace(controlMarker, calendarNav + controlMarker);
    const spacer = '<div class="wb-rail-spacer"></div>';
    const rail = `<button class="wb-rail-button ${activeView==='calendar'?'active':''}" data-view="calendar" title="Kalender">${icon('spark',18)}</button>`;
    if (markup.includes(spacer)) markup = markup.replace(spacer, rail + spacer);
    return markup;
  };

  renderDashboard = function calendarAwareRenderDashboard() {
    if (activeView === 'calendar') {
      app.innerHTML = dashboardLayout(calendarPage());
      bindDashboard();
      bindCalendar();
      if (!cal.status && !cal.loading) window.setTimeout(refreshPage, 0);
      return;
    }
    originalRenderDashboard();
    injectMailBridge();
  };

  window.__mailAgentCalendar = cal;
})();
