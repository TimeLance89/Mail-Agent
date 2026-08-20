(() => {
  let runtimeVersion = '';

  async function refreshRuntimeVersion() {
    try {
      const response = await fetch('/health', {cache:'no-store'});
      if (!response.ok) return;
      const payload = await response.json();
      runtimeVersion = String(payload.version || payload.app_version || '').replace(/^v/i, '').trim();
      applyRuntimeVersion();
    } catch (_) {}
  }

  function applyRuntimeVersion() {
    const version = runtimeVersion || String(updateStatus?.current_version || '').replace(/^v/i, '').trim();
    if (!version) return;
    document.querySelectorAll('.wb-build').forEach(node => { node.textContent = version; });
    document.querySelectorAll('.su-kicker').forEach(node => {
      node.textContent = node.textContent.replace(/\b\d+\.\d+\.\d+\b/, version);
    });
  }

  async function discardWorkbenchDraft(draftId) {
    const item = (dashboard.drafts || []).find(draft => String(draft.draft_id) === String(draftId));
    if (!item) return;
    const question = item.approval_id
      ? 'Diesen Entwurf und seine offene Versandfreigabe wirklich ablehnen und verwerfen?'
      : 'Diesen Entwurf wirklich verwerfen?';
    if (!window.confirm(question)) return;
    try {
      await post(`/v1/drafts/${encodeURIComponent(draftId)}/discard`, {actor:'local-user'});
      if (editingDraftId === draftId) editingDraftId = null;
      await loadDashboard(true);
      showNotice('Entwurf verworfen.');
      render();
    } catch (error) {
      showNotice(error.message, 'error');
    }
  }

  function exposeWorkbenchDiscard() {
    if (activeView !== 'drafts') return;
    const footer = document.querySelector('.wb-detail-footer');
    if (!footer || footer.querySelector('[data-draft-discard]')) return;
    if (footer.querySelector('[data-draft-save]')) return;
    const anchor = footer.querySelector('[data-draft-edit], [data-draft-submit]');
    const draftId = anchor?.dataset.draftEdit || anchor?.dataset.draftSubmit || '';
    if (!draftId) return;
    const item = (dashboard.drafts || []).find(draft => String(draft.draft_id) === String(draftId));
    if (!item || ['sent','discarded'].includes(String(item.status || ''))) return;
    const button = document.createElement('button');
    button.className = 'wb-btn danger';
    button.dataset.draftDiscard = draftId;
    button.textContent = item.approval_id ? 'Ablehnen & verwerfen' : 'Verwerfen';
    button.onclick = () => discardWorkbenchDraft(draftId);
    footer.prepend(button);
  }

  async function ensureCalendarMailFollowup(calendarApprovalId) {
    try {
      const response = await fetch(
        `/v1/calendar/approvals/${encodeURIComponent(calendarApprovalId)}/prepare-mail-reply?actor=local-user`,
        {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json'}},
      );
      const payload = await response.json().catch(() => ({}));
      if (response.ok && payload.mail_followup?.approval) {
        await loadDashboard(true);
        showNotice('Termin eingetragen. Die Bestätigungsantwort ist vorbereitet und wartet unter „Freigaben“ auf Freigeben & senden.');
        render();
        return;
      }
      const detail = String(payload.detail || '');
      if (response.status === 409 && /not linked|nicht.*mail|needs confirmation/i.test(detail)) return;
      if (response.status === 409 && /approved and completed|approved.*completed/i.test(detail)) {
        window.setTimeout(() => ensureCalendarMailFollowup(calendarApprovalId), 900);
        return;
      }
      if (!response.ok && detail) showNotice(detail, 'error');
    } catch (error) {
      showNotice(error.message, 'error');
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-su-approve]');
    if (!button) return;
    const approvalId = button.dataset.suApprove;
    if (!approvalId) return;
    window.setTimeout(() => ensureCalendarMailFollowup(approvalId), 900);
  });

  const previousRenderDashboard = renderDashboard;
  renderDashboard = function v172RenderDashboard() {
    const result = previousRenderDashboard();
    applyRuntimeVersion();
    exposeWorkbenchDiscard();
    return result;
  };

  refreshRuntimeVersion();
  applyRuntimeVersion();
  exposeWorkbenchDiscard();
})();
