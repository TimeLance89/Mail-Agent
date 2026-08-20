(() => {
  let cachedMailbox = '';
  let cachedSuggestions = [];
  let loadedAt = 0;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));
  const labels = {
    availability:'Verfügbarkeit gefragt',
    reschedule:'Verschiebung angefragt',
    cancellation:'Absage / Storno',
    schedule_request:'Terminbezug erkannt',
  };

  async function api(path, options={}) {
    const response = await fetch(path, {
      cache:'no-store',
      headers:{'Content-Type':'application/json'},
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`);
    return payload;
  }

  async function suggestionsFor(mailboxId) {
    if (cachedMailbox === mailboxId && Date.now() - loadedAt < 30000) return cachedSuggestions;
    const result = await api(`/v1/calendar/mail-suggestions?mailbox_id=${encodeURIComponent(mailboxId)}&limit=120`);
    cachedMailbox = mailboxId;
    cachedSuggestions = result.suggestions || [];
    loadedAt = Date.now();
    return cachedSuggestions;
  }

  async function availabilityReply(item) {
    const calendar = window.__mailAgentCalendar;
    if (!calendar?.mailboxId) throw new Error('Google Kalender ist nicht verbunden.');
    if (calendar.mailboxId !== item.mailbox_id) {
      throw new Error('Der Kalender ist derzeit mit einem anderen Google-Postfach verbunden.');
    }
    const result = await api('/v1/calendar/mail-reply', {
      method:'POST',
      body:JSON.stringify({
        mailbox_id:calendar.mailboxId,
        source_message_id:item.message_id,
        calendar_id:calendar.calendarId || 'primary',
        duration_minutes:60,
        slot_count:3,
        actor:'local-user',
      }),
    });
    await loadDashboard(true);
    activeView='drafts';
    if (typeof showNotice === 'function') showNotice(`${result.free_slots?.length||0} verifizierte freie Zeiten als Antwortentwurf vorbereitet.`);
    render();
  }

  function planFromMail(item) {
    const calendar = window.__mailAgentCalendar;
    if (!calendar) return;
    calendar.sourceMessageId=item.message_id;
    calendar.sourceSubject=item.subject||'';
    const prompts = {
      availability:'Hilf mir auf diese Terminmail zu reagieren. Prüfe meinen Kalender und schlage einen passenden nächsten Schritt vor. Wenn Angaben fehlen, frage mich.',
      reschedule:'Prüfe die Verschiebungsanfrage aus dieser Mail gegen meinen Kalender. Verändere nichts ohne einen konkreten Vorschlag und meine Freigabe.',
      cancellation:'Ordne die Absage aus dieser Mail dem passenden vorhandenen Termin zu. Wenn nicht eindeutig, frage mich statt einen Termin zu löschen.',
      schedule_request:'Prüfe diese Terminmail und hilf mir bei der Planung anhand meiner echten Kalenderdaten.',
    };
    const input=document.getElementById('cw-instruction');
    if(input){input.value=prompts[item.intent]||prompts.schedule_request;input.focus();window.scrollTo({top:0,behavior:'smooth'});}
    if (typeof showNotice === 'function') showNotice('Mail als untrusted Kalender-Kontext übernommen.');
  }

  function correctSharedCalendarRoleLabels() {
    const calendar = window.__mailAgentCalendar;
    const select = document.getElementById('cw-calendar');
    if (!calendar || !select) return;
    const roles = new Map(
      (calendar.calendars || []).map(item => [
        String(item.id || ''),
        String(item.access_role || '').toLowerCase(),
      ])
    );
    const writable = new Set(['owner', 'writer', 'writerwithoutprivateaccess']);
    [...select.options].forEach(option => {
      if (writable.has(roles.get(String(option.value)) || '')) {
        option.textContent = option.textContent.replace(/\s*·\s*nur lesen\s*$/, '');
      }
    });
  }

  async function mountSuggestions() {
    if (activeView !== 'calendar') return;
    correctSharedCalendarRoleLabels();
    const shell=document.querySelector('.cw-shell');
    if(!shell || shell.querySelector('#cw-mail-suggestions')) return;
    const mailbox=dashboard.mailboxes?.[0];
    if(!mailbox) return;
    const section=document.createElement('section');
    section.id='cw-mail-suggestions';
    section.className='cw-card full';
    section.innerHTML='<div class="cw-empty">Terminwünsche aus Mails werden geprüft …</div>';
    const hero=shell.querySelector('.cw-hero');
    if(hero)hero.insertAdjacentElement('afterend',section);else shell.prepend(section);
    try{
      const items=await suggestionsFor(mailbox.mailbox_id);
      if(!section.isConnected || activeView!=='calendar')return;
      section.innerHTML=`<div class="cw-head"><div><h3>Terminwünsche aus E-Mails</h3><p>Deterministisch erkannt. Mail-Inhalte bleiben untrusted und lösen niemals selbst eine Kalenderänderung aus.</p></div><span class="cw-tag">${items.length} Hinweis${items.length===1?'':'e'}</span></div>${items.length?items.slice(0,8).map((item,index)=>`<div class="cw-row"><div><b>${esc(item.subject||'(ohne Betreff)')}</b><small>${esc(item.sender||'')} · ${esc(labels[item.intent]||item.intent)}${item.has_explicit_time?' · konkrete Uhrzeit erkannt':''}</small></div><div class="cw-actions"><button class="cw-btn" data-cwm-plan="${index}">Mit Kalender prüfen</button>${item.intent==='availability'?`<button class="cw-btn primary" data-cwm-reply="${index}">Freie Zeiten antworten</button>`:''}</div></div>`).join(''):'<div class="cw-empty">Aktuell wurde keine Mail mit ausreichend starkem Terminbezug erkannt.</div>'}`;
      section.querySelectorAll('[data-cwm-plan]').forEach(button=>button.addEventListener('click',()=>planFromMail(items[Number(button.dataset.cwmPlan)])));
      section.querySelectorAll('[data-cwm-reply]').forEach(button=>button.addEventListener('click',()=>availabilityReply(items[Number(button.dataset.cwmReply)]).catch(error=>showNotice?.(error.message,'error'))));
    }catch(error){
      if(section.isConnected)section.innerHTML=`<div class="cw-empty">Mail-Terminhinweise konnten nicht geladen werden: ${esc(error.message)}</div>`;
    }
  }

  const previousRenderDashboard=renderDashboard;
  renderDashboard=function calendarMailAwareRenderDashboard(){
    previousRenderDashboard();
    if(activeView==='calendar'){
      correctSharedCalendarRoleLabels();
      window.setTimeout(mountSuggestions,0);
    }
  };
})();
