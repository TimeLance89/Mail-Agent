(() => {
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
  if (!allowed.has(requested)) return;

  let applied = false;
  const apply = () => {
    if (applied) return true;
    const target = document.querySelector(`[data-view="${requested}"]`);
    if (!target) return false;
    applied = true;
    target.click();
    const clean = requested === 'overview' ? '/' : `/?view=${encodeURIComponent(requested)}`;
    window.history.replaceState({}, '', clean);
    return true;
  };

  if (apply()) return;
  const observer = new MutationObserver(() => {
    if (apply()) observer.disconnect();
  });
  observer.observe(document.getElementById('app'), { childList: true, subtree: true });
  window.setTimeout(() => observer.disconnect(), 15000);
})();
