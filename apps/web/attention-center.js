(() => {
  const apiBase = location.origin;
  let attention = [];
  let settingsCache = null;
  let renderingAttention = false;

  const escHtml = value => String(value ?? '').replace(/[&<>\"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const request = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };
  const notify = (text, kind = 'success') => {
    if (typeof window.showNotice === 'function') window.showNotice(text, kind);
  };
  const messageId = item => String(item.remote_id || item.internet_message_id || item.uid || '');
  const isAttentionRoute = () => new URLSearchParams(location.search).get('view') === 'attention';

  async function loadAttention() {
    const data = await request('/v1/attention?limit=200');
    attention = data.attention || [];
    updateNavBadge();
    return attention;
  }

  function attentionLabel(item) {
    if (item.needs_reply === true) return 'Antwort / Entscheidung nötig';
    if (item.agent_priority === 'urgent') return 'Dringend';
    if (item.agent_category === 'security') return 'Sicherheitsrelevant';
    return 'Wichtig';
  }

  function attentionCard(item) {
    const id = messageId(item);
    const summary = item.agent_summary || 'Der Agent hat diese Mail als relevant für deine Aufmerksamkeit eingestuft.';
    const priority = item.agent_priority || 'normal';
    const category = item.agent_category || 'other';
    return `<article class="attention-card">
      <div class="attention-head"><div><span class="attention-kicker">${escHtml(attentionLabel(item))}</span><h3>${escHtml(item.subject || '(ohne Betreff)')}</h3><p>${escHtml(item.sender || '')}</p></div><span class="intel-badge ${escHtml(priority)}">${escHtml(priority)}</span></div>
      <div class="attention-tags"><span>${escHtml(category)}</span>${item.needs_reply === true ? '<span>Antwort nötig</span>' : ''}${item.attention_source === 'shadow' ? '<span>Shadow-Ergebnis</span>' : ''}</div>
      <p class="attention-summary">${escHtml(summary)}</p>
      <label class="field"><span>Meine Rückmeldung / Notiz</span><textarea rows="3" data-attention-note="${escHtml(id)}" placeholder="Optional: Entscheidung, Kontext oder Notiz für dich …">${escHtml(item.owner_note || '')}</textarea></label>
      <div class="inline-actions left"><button class="btn primary compact" data-attention-resolve="${escHtml(id)}" data-mailbox="${escHtml(item.mailbox_id)}">Erledigt / Rückmeldung speichern</button></div>
    </article>`;
  }

  async function renderAttention() {
    if (renderingAttention) return;
    renderingAttention = true;
    try {
      await loadAttention();
      const body = document.querySelector('.workspace-body');
      if (!body) return;
      const title = document.querySelector('.topbar h1');
      if (title) title.textContent = 'Handlungsbedarf';
      body.innerHTML = `<div class="attention-center"><section class="panel attention-hero"><div><span class="hero-kicker">DEINE ENTSCHEIDUNGEN</span><h2>Was deine Aufmerksamkeit braucht.</h2><p>Hier bündelt MAIL-AGENT wichtige, dringende, sicherheitsrelevante oder antwortbedürftige Mails. Freigaben für riskante Aktionen bleiben separat in der Freigabe-Queue.</p></div><span class="badge">${attention.length} OFFEN</span></section><section class="panel full"><div class="panel-head"><div><span>WARTET AUF DICH</span><h3>Handlungsbedarf</h3></div><button class="btn secondary compact" id="attention-refresh">Aktualisieren</button></div>${attention.length ? `<div class="attention-list">${attention.map(attentionCard).join('')}</div>` : '<div class="empty-state large"><b>Alles erledigt</b><span>Aktuell wartet keine wichtige Mail auf deine Aufmerksamkeit.</span></div>'}</section></div>`;
      document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === 'attention'));
      document.getElementById('attention-refresh')?.addEventListener('click', renderAttention);
      document.querySelectorAll('[data-attention-resolve]').forEach(button => button.addEventListener('click', async () => {
        const id = button.dataset.attentionResolve;
        const mailboxId = button.dataset.mailbox;
        const note = document.querySelector(`[data-attention-note="${CSS.escape(id)}"]`)?.value?.trim() || null;
        button.disabled = true;
        try {
          await request('/v1/attention/resolve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mailbox_id:mailboxId,message_id:id,owner_note:note,actor:'local-user'})});
          notify('Handlungsbedarf als erledigt markiert.');
          await renderAttention();
        } catch (error) {
          notify(error.message, 'error');
          button.disabled = false;
        }
      }));
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      renderingAttention = false;
    }
  }

  function updateNavBadge() {
    const button = document.querySelector('[data-view="attention"]');
    if (!button) return;
    let badge = button.querySelector('b');
    if (attention.length) {
      if (!badge) { badge = document.createElement('b'); button.appendChild(badge); }
      badge.textContent = String(attention.length);
    } else if (badge) badge.remove();
  }

  function injectAttentionNav() {
    const nav = document.querySelector('.sidebar nav');
    if (!nav || nav.querySelector('[data-view="attention"]')) return;
    const button = document.createElement('button');
    button.className = 'nav-item';
    button.dataset.view = 'attention';
    button.innerHTML = `<svg class="icon" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z"/><path d="M12 8v5"/><path d="M12 17h.01"/></svg><span>Handlungsbedarf</span>`;
    const approvals = nav.querySelector('[data-view="approvals"]');
    nav.insertBefore(button, approvals || null);
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      history.replaceState({}, '', '/?view=attention');
      renderAttention();
    });
    updateNavBadge();
  }

  async function injectMailAutomationSettings() {
    const marker = document.getElementById('behavior-auto-drafts');
    if (!marker || document.getElementById('behavior-mail-automation')) return;
    try {
      settingsCache = await request('/v1/settings');
      const behavior = settingsCache.behavior || {};
      const row = marker.closest('.setting-row');
      if (!row) return;
      const wrapper = document.createElement('div');
      wrapper.id = 'behavior-mail-automation';
      wrapper.className = 'mail-automation-settings';
      const options = value => `<option value="none" ${value==='none'?'selected':''}>Nur analysieren</option><option value="mark_read" ${value==='mark_read'?'selected':''}>Automatisch als gelesen markieren</option><option value="archive" ${value==='archive'?'selected':''}>Automatisch archivieren, wenn Policy erlaubt</option>`;
      wrapper.innerHTML = `<div class="setting-row"><span>Erfolgreich abgearbeitete Mails im Postfach als gelesen markieren</span><input id="behavior-mark-processed-read" type="checkbox" ${behavior.mark_processed_read !== false ? 'checked' : ''}></div><div class="form-grid two"><label class="field"><span>Newsletter automatisch behandeln</span><select id="behavior-newsletter-action">${options(behavior.newsletter_action || 'none')}</select></label><label class="field"><span>Werbung automatisch behandeln</span><select id="behavior-advertising-action">${options(behavior.advertising_action || 'none')}</select></label></div><div class="security-note"><span>Archivieren bleibt an Autonomie und Policy Engine gebunden. Shadow Mode verändert niemals das Postfach.</span></div><div class="inline-actions left"><button class="btn secondary compact" id="save-mail-automation">Mail-Automatik speichern</button></div>`;
      row.insertAdjacentElement('afterend', wrapper);
      document.getElementById('save-mail-automation')?.addEventListener('click', async () => {
        const latest = await request('/v1/settings');
        const next = {...(latest.behavior || {}), mark_processed_read:!!document.getElementById('behavior-mark-processed-read')?.checked, newsletter_action:document.getElementById('behavior-newsletter-action')?.value || 'none', advertising_action:document.getElementById('behavior-advertising-action')?.value || 'none'};
        try {
          settingsCache = await request('/v1/settings/behavior', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({behavior:next})});
          if (typeof window.loadRuntimeSettings === 'function') await window.loadRuntimeSettings(true);
          notify('Mail-Automatik gespeichert.');
        } catch (error) {
          notify(error.message, 'error');
        }
      });
    } catch (error) {
      // Settings remain usable even if this enhancement cannot load.
    }
  }

  function enhance() {
    injectAttentionNav();
    injectMailAutomationSettings();
    loadAttention().catch(() => undefined);
    if (isAttentionRoute()) renderAttention();
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-view]');
    if (!target || target.dataset.view === 'attention') return;
    if (isAttentionRoute()) {
      const view = target.dataset.view;
      history.replaceState({}, '', view === 'overview' ? '/' : `/?view=${encodeURIComponent(view)}`);
    }
  }, true);

  const app = document.getElementById('app');
  if (app) {
    new MutationObserver(() => setTimeout(enhance, 0)).observe(app, {childList:true});
  }
  setTimeout(enhance, 0);
  window.setInterval(() => loadAttention().catch(() => undefined), 30000);
})();
