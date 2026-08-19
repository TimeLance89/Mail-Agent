(() => {
  const APP_VERSION = '0.13.0';
  const allowed = new Set([
    'overview',
    'activity',
    'shadow',
    'system',
    'inbox',
    'approvals',
    'drafts',
    'settings',
  ]);
  const requested = new URLSearchParams(window.location.search).get('view');
  let deepLinkApplied = false;

  const applyDeepLink = () => {
    if (deepLinkApplied || !allowed.has(requested)) return deepLinkApplied;
    const target = document.querySelector(`[data-view="${requested}"]`);
    if (!target) return false;
    deepLinkApplied = true;
    target.click();
    const clean = requested === 'overview' ? '/' : `/?view=${encodeURIComponent(requested)}`;
    window.history.replaceState({}, '', clean);
    return true;
  };

  const applyVersion = () => {
    const footer = document.querySelector('.setup-foot');
    if (footer) footer.textContent = `MAIL-AGENT v${APP_VERSION} · Lokales Gateway`;
  };

  const statusLabel = (settings, brain, health) => {
    const behavior = settings?.behavior || {};
    if (health?.overall === 'action_required') return 'Aktion erforderlich';
    if (behavior.enabled === false) return 'Pausiert';
    if (behavior.execution_mode === 'shadow') return 'Shadow Mode';
    if (Number(brain?.pending_total || 0) > 0) return 'Arbeit vorhanden';
    return 'Aktiv';
  };

  const applyLiveStatus = async () => {
    try {
      const [settingsResponse, brainResponse, healthResponse] = await Promise.all([
        fetch('/v1/settings'),
        fetch('/v1/agent/brain'),
        fetch('/v1/system/health'),
      ]);
      if (![settingsResponse, brainResponse, healthResponse].every(response => response.ok)) return;
      const [settings, brain, health] = await Promise.all([
        settingsResponse.json(),
        brainResponse.json(),
        healthResponse.json(),
      ]);
      const label = statusLabel(settings, brain, health);
      const agentStatus = document.querySelector('.agent-mini small');
      if (agentStatus) agentStatus.innerHTML = `<i></i> ${label}`;
      const gatewayStatus = document.querySelector('.status-pill');
      if (gatewayStatus) gatewayStatus.innerHTML = `<i></i> ${label}`;
    } catch (_) {
      // The main UI already surfaces gateway errors; this helper must stay non-blocking.
    }
  };

  const apply = () => {
    applyDeepLink();
    applyVersion();
  };

  apply();
  const observer = new MutationObserver(apply);
  const app = document.getElementById('app');
  if (app) observer.observe(app, { childList: true, subtree: true });
  window.setTimeout(() => observer.disconnect(), 15000);

  applyLiveStatus();
  window.setInterval(applyLiveStatus, 15000);
})();
