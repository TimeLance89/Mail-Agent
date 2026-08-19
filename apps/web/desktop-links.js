(() => {
  const APP_VERSION = '0.13.6';
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
    const text = `MAIL-AGENT v${APP_VERSION} · Lokales Gateway`;
    if (footer && footer.textContent !== text) footer.textContent = text;
  };

  const apply = () => {
    applyDeepLink();
    applyVersion();
  };

  apply();
  const observer = new MutationObserver(apply);
  const app = document.getElementById('app');
  if (app) observer.observe(app, { childList: true });
  window.setTimeout(() => observer.disconnect(), 15000);
})();
