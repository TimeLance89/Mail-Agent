/* MAIL-AGENT Conversation Intelligence UI adapter. */
(() => {
  const VERSION = '0.18.2';
  let shownUndoToken = '';
  let pollTimer = null;

  if (typeof setupLayout === 'function') {
    const originalSetupLayout = setupLayout;
    setupLayout = function conversationSetupLayout(content) {
      return originalSetupLayout(content).replace(/MAIL-AGENT v[0-9.]+ · Lokales Gateway/g, `MAIL-AGENT v${VERSION} · Lokales Gateway`);
    };
  }

  if (typeof ruleRow === 'function') {
    const originalRuleRow = ruleRow;
    ruleRow = function conversationRuleRow(rule, index) {
      let html = originalRuleRow(rule, index);
      const category = String(rule?.category || '');
      const extra = [
        `<option value="advertising" ${category === 'advertising' ? 'selected' : ''}>advertising</option>`,
        `<option value="cold_outreach" ${category === 'cold_outreach' ? 'selected' : ''}>cold_outreach</option>`,
      ].join('');
      return html.replace('<option value="newsletter"', `${extra}<option value="newsletter"`);
    };
  }

  function removeBanner() {
    document.getElementById('conversation-undo-banner')?.remove();
  }

  async function applyUndo(token) {
    try {
      const result = await post(`/v1/actions/undo/${encodeURIComponent(token)}`, { actor: 'local-user' });
      removeBanner();
      shownUndoToken = '';
      showNotice('Mailbox-Aktion rückgängig gemacht.');
      if (result.resync_required && typeof syncNow === 'function') {
        await syncNow();
      } else if (typeof loadDashboard === 'function') {
        await loadDashboard(true);
        render();
      }
    } catch (error) {
      showNotice(error.message, 'error');
      removeBanner();
    }
  }

  function showUndo(item) {
    if (!item?.token || item.token === shownUndoToken) return;
    const remaining = Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000));
    if (!remaining) return;
    shownUndoToken = item.token;
    removeBanner();
    const banner = document.createElement('div');
    banner.id = 'conversation-undo-banner';
    banner.className = 'conversation-undo-banner';
    const label = item.action === 'archive' ? 'Mail archiviert' : item.action === 'mark_read' ? 'Mail als gelesen markiert' : 'Mailbox-Aktion ausgeführt';
    banner.innerHTML = `<div><strong>${esc(label)}</strong><span>Rückgängig noch ${remaining}s möglich</span></div><button type="button">Rückgängig</button>`;
    banner.querySelector('button')?.addEventListener('click', () => applyUndo(item.token));
    document.body.appendChild(banner);
    const timer = window.setInterval(() => {
      const left = Math.max(0, Math.ceil((new Date(item.expires_at).getTime() - Date.now()) / 1000));
      const text = banner.querySelector('span');
      if (text) text.textContent = left ? `Rückgängig noch ${left}s möglich` : 'Rückgängig abgelaufen';
      if (!left) {
        window.clearInterval(timer);
        window.setTimeout(removeBanner, 700);
      }
    }, 500);
  }

  async function refreshUndo() {
    if (typeof installed !== 'undefined' && !installed) return;
    try {
      const payload = await get('/v1/conversations?limit=1');
      const item = (payload.undo_actions || [])[0];
      if (item) showUndo(item);
    } catch (_) {
      // UI convenience must never disturb the main application.
    }
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const raw = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if (response.ok && String(raw).includes('/v1/agent/run')) {
        window.setTimeout(refreshUndo, 100);
      }
    } catch (_) {}
    return response;
  };

  window.setTimeout(refreshUndo, 700);
  pollTimer = window.setInterval(refreshUndo, 2500);
  window.addEventListener('beforeunload', () => pollTimer && window.clearInterval(pollTimer), { once: true });

  const style = document.createElement('style');
  style.textContent = `.conversation-undo-banner{position:fixed;right:24px;bottom:24px;z-index:10050;display:flex;align-items:center;gap:18px;min-width:330px;padding:14px 14px 14px 16px;background:#1a1916;border:1px solid rgba(201,166,96,.5);box-shadow:0 18px 54px rgba(0,0,0,.38);color:#f1eee7}.conversation-undo-banner div{display:grid;gap:3px;flex:1}.conversation-undo-banner strong{font-size:13px}.conversation-undo-banner span{font-size:12px;color:#aaa49a}.conversation-undo-banner button{border:1px solid rgba(201,166,96,.55);background:#c9a660;color:#15130f;padding:9px 12px;font-weight:700;cursor:pointer}`;
  document.head.appendChild(style);
})();
