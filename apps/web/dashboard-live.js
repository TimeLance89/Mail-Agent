(() => {
  const POLL_MS = 15000;
  let refreshInFlight = false;
  let applyingStatus = false;
  let lastErrorMessage = '';
  let lastErrorAt = 0;

  const rawShowNotice = showNotice;

  function friendlyErrorMessage(value) {
    const text = String(value || '').trim();
    if (!text) return 'Die Aktion konnte nicht abgeschlossen werden.';
    if (/failed to fetch|networkerror|load failed|econnrefused|connection refused|connecterror|http 5\d\d/i.test(text)) {
      return 'Das lokale Gateway antwortet gerade nicht. Prüfe, ob MAIL-AGENT noch läuft, und versuche es erneut.';
    }
    if (/timed?\s*out|timeout/i.test(text)) {
      return 'Die Anfrage dauert ungewöhnlich lange. Bitte versuche es gleich noch einmal.';
    }
    if (/401|403|unauthori[sz]ed|forbidden|permission denied/i.test(text)) {
      return 'Diese Aktion wurde aus Sicherheitsgründen abgelehnt. Prüfe die Verbindung oder Freigabe und versuche es erneut.';
    }
    if (/oauth|token|credential|vault/i.test(text) && /mail|gmail|google|microsoft|graph|imap|smtp|postfach/i.test(text)) {
      return 'Die Postfach-Verbindung ist nicht mehr vollständig gültig. Bitte verbinde das Postfach erneut.';
    }
    if (/imap|smtp|gmail|microsoft graph|mailbox|postfach|sync/i.test(text)) {
      return 'Das Postfach konnte gerade nicht vollständig synchronisiert werden. Öffne den Systemzustand für Details oder starte den Sync erneut.';
    }
    if (/provider|ollama|codex|model|llm/i.test(text)) {
      return 'Das ausgewählte KI-Modell ist momentan nicht bereit. Prüfe den Provider in den Einstellungen.';
    }
    if (/already been decided|already decided/i.test(text)) {
      return 'Diese Freigabe wurde bereits entschieden. Die Ansicht wird aktualisiert.';
    }
    if (/already in progress|in progress|could not be claimed/i.test(text)) {
      return 'Diese Aktion wird bereits ausgeführt. Bitte warte auf den aktuellen Status.';
    }
    if (/http \d{3}/i.test(text)) {
      return 'Die Aktion konnte nicht abgeschlossen werden. Öffne den Systemzustand und versuche es erneut.';
    }
    return text;
  }

  showNotice = function dashboardFriendlyNotice(text, kind = 'success') {
    const message = kind === 'error' ? friendlyErrorMessage(text) : String(text || '');
    if (kind === 'error') {
      const now = Date.now();
      if (message === lastErrorMessage && now - lastErrorAt < 60000) return;
      lastErrorMessage = message;
      lastErrorAt = now;
    }
    rawShowNotice(message, kind);
  };

  function importantMessages() {
    const messages = dashboard?.messages || [];
    return messages.filter(item => {
      const priority = String(item.agent_priority || '').toLowerCase();
      const category = String(item.agent_category || '').toLowerCase();
      return priority === 'urgent' || priority === 'high' || (category === 'security' && item.needs_reply === true);
    });
  }

  function liveStatus() {
    const behavior = runtimeSettings?.behavior || {};
    const health = systemHealth || {};
    const summary = health.summary || {};
    const approvalCount = Number(dashboard?.approvals?.length || 0);
    const draftCount = Number(dashboard?.drafts?.filter(item => item.status !== 'sent').length || 0);
    const pendingCount = Number(brainStatus?.pending_total || 0);
    const importantCount = importantMessages().length;

    if (health.overall === 'action_required' || Number(summary.error || 0) > 0) {
      return { key: 'error', label: 'Aktion erforderlich', detail: 'Mindestens ein Bereich braucht deine Aufmerksamkeit.', importantCount };
    }
    if (behavior.enabled === false) {
      return { key: 'paused', label: 'Pausiert', detail: 'Der Agent analysiert und bearbeitet aktuell keine neuen Mails.', importantCount };
    }
    if (behavior.execution_mode === 'shadow') {
      return { key: 'shadow', label: 'Shadow Mode', detail: 'Analyse läuft sicher ohne produktive Mail-Aktionen.', importantCount };
    }
    if (busy || brainLoading || shadowLoading || systemHealthLoading) {
      return { key: 'busy', label: 'Arbeitet', detail: 'MAIL-AGENT aktualisiert gerade lokale Zustände.', importantCount };
    }
    if (health.overall === 'degraded' || Number(summary.warning || 0) > 0) {
      return { key: 'warning', label: 'Hinweis prüfen', detail: 'MAIL-AGENT läuft weiter, aber ein Bereich sollte geprüft werden.', importantCount };
    }
    if (approvalCount || draftCount || pendingCount) {
      const parts = [];
      if (approvalCount) parts.push(`${approvalCount} Freigabe${approvalCount === 1 ? '' : 'n'}`);
      if (draftCount) parts.push(`${draftCount} Entwurf${draftCount === 1 ? '' : 'e'}`);
      if (pendingCount) parts.push(`${pendingCount} Mail${pendingCount === 1 ? '' : 's'} warten`);
      return { key: 'work', label: 'Arbeit vorhanden', detail: parts.join(' · '), importantCount };
    }
    return { key: 'active', label: 'Aktiv', detail: 'Gateway, Postfach und Agent sind bereit.', importantCount };
  }

  function dotColor(key) {
    return ({
      error: 'var(--red)',
      warning: '#f4ba82',
      paused: '#8794a9',
      shadow: 'var(--accent-2)',
      busy: 'var(--accent)',
      work: 'var(--green)',
      active: 'var(--green)',
    })[key] || 'var(--green)';
  }

  function setBadge(view, value) {
    const button = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (!button) return;
    let badge = button.querySelector('b');
    const text = String(value || '');
    if (!text || text === '0') {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = document.createElement('b');
      button.appendChild(badge);
    }
    if (badge.textContent !== text) badge.textContent = text;
  }

  function applyLiveStatus() {
    if (!installed || applyingStatus) return;
    applyingStatus = true;
    try {
      const status = liveStatus();
      const color = dotColor(status.key);
      const statusHtml = `<i style="background:${color}"></i> ${esc(status.label)}`;

      const mini = document.querySelector('.agent-mini small');
      if (mini && mini.dataset.liveStatus !== status.key) {
        mini.dataset.liveStatus = status.key;
        mini.innerHTML = statusHtml;
      }
      const pill = document.querySelector('.status-pill');
      if (pill) {
        const signature = `${status.key}|${status.detail}`;
        if (pill.dataset.liveStatus !== signature) {
          pill.dataset.liveStatus = signature;
          pill.innerHTML = statusHtml;
          pill.title = status.detail;
        }
      }

      const body = document.querySelector('.workspace-body');
      if (body) {
        let strip = document.getElementById('live-state-strip');
        if (!strip) {
          strip = document.createElement('div');
          strip.id = 'live-state-strip';
          strip.className = 'security-note';
          strip.style.marginBottom = '18px';
          body.prepend(strip);
        }
        const signature = `${status.key}|${status.detail}|${status.importantCount}`;
        if (strip.dataset.signature !== signature) {
          strip.dataset.signature = signature;
          const important = status.importantCount
            ? `<span class="badge soft">${esc(status.importantCount)} wichtig</span>`
            : '';
          strip.innerHTML = `${icon(status.key === 'error' ? 'shield' : 'spark', 18)}<span><b>${esc(status.label)}</b><small>${esc(status.detail)}</small></span>${important}`;
        }
      }

      setBadge('activity', brainStatus?.pending_total || '');
      setBadge('system', systemHealth?.summary?.error || systemHealth?.summary?.warning || '');
      setBadge('inbox', dashboard?.messages?.length || '');
      setBadge('approvals', dashboard?.approvals?.length || '');
      setBadge('drafts', dashboard?.drafts?.length || '');
      setBadge('shadow', runtimeSettings?.behavior?.execution_mode === 'shadow' ? 'SHADOW' : '');

      if (activeView === 'overview') {
        const kicker = document.querySelector('.hero-card .hero-kicker');
        if (kicker) {
          const text = status.label.toUpperCase();
          if (kicker.textContent !== text) kicker.textContent = text;
        }
      }
    } finally {
      applyingStatus = false;
    }
  }

  async function refreshLiveState() {
    if (!installed || refreshInFlight || document.visibilityState === 'hidden') return;
    refreshInFlight = true;
    try {
      const tasks = [
        loadDashboard(true),
        loadRuntimeSettings(true),
        loadBrainStatus(true),
        loadSystemHealth(true),
      ];
      if (window.__mailAgentWorkbench?.refreshBriefing) {
        tasks.push(window.__mailAgentWorkbench.refreshBriefing(true));
      }
      if (activeView === 'shadow' || runtimeSettings?.behavior?.execution_mode === 'shadow') {
        tasks.push(loadShadowStatus(true));
      }
      await Promise.allSettled(tasks);

      const safeToRender = !busy && !editingDraftId && ['overview', 'activity', 'system', 'inbox', 'approvals', 'drafts'].includes(activeView);
      if (safeToRender) render();
      else applyLiveStatus();
    } finally {
      refreshInFlight = false;
    }
  }

  const appRoot = document.getElementById('app');
  if (appRoot) {
    const observer = new MutationObserver(() => applyLiveStatus());
    observer.observe(appRoot, { childList: true });
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshLiveState();
  });

  window.setTimeout(() => {
    applyLiveStatus();
    refreshLiveState();
  }, 1000);
  window.setInterval(refreshLiveState, POLL_MS);
})();
