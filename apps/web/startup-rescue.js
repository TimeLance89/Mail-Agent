(() => {
  const appRoot = document.getElementById('app');
  if (!appRoot) return;

  const BACKGROUND_WAIT_MS = 6000;
  let runtimeTask = null;
  let systemHealthTask = null;

  const timeout = ms => new Promise(resolve => window.setTimeout(resolve, ms));

  function backgroundLoader(original, taskName) {
    return function nonBlockingLoader(silent = false) {
      let task = taskName === 'runtime' ? runtimeTask : systemHealthTask;
      if (!task) {
        task = Promise.resolve()
          .then(() => original(true))
          .catch(() => undefined)
          .finally(() => {
            if (taskName === 'runtime') runtimeTask = null;
            else systemHealthTask = null;
          });
        if (taskName === 'runtime') runtimeTask = task;
        else systemHealthTask = task;
      }

      // Silent startup/live refreshes must never keep #app empty while a provider
      // or diagnostic subprocess is slow. The real task continues in the background.
      if (silent) return Promise.resolve();

      // User-triggered views may wait briefly for fresh data, but the navigation
      // itself must still recover even if an external provider never answers.
      return Promise.race([task, timeout(BACKGROUND_WAIT_MS)]);
    };
  }

  try {
    if (typeof loadRuntimeSettings === 'function') {
      loadRuntimeSettings = backgroundLoader(loadRuntimeSettings, 'runtime');
    }
    if (typeof loadSystemHealth === 'function') {
      loadSystemHealth = backgroundLoader(loadSystemHealth, 'health');
    }
  } catch (_) {
    // app.js remains authoritative; this guard only removes optional startup blockers.
  }

  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    window.clearInterval(renderTimer);
  };

  const renderTimer = window.setInterval(() => {
    if (appRoot.querySelector('.dashboard, .setup-page')) {
      finish();
      return;
    }
    try {
      // boot() sets installed immediately after /v1/onboarding/status, before it
      // starts the optional dashboard/settings/health enrichment requests.
      if (typeof installed !== 'undefined' && installed === true && typeof render === 'function') {
        render();
        finish();
      }
    } catch (_) {
      // Keep the static startup shell visible until app.js can render normally.
    }
  }, 50);

  window.setTimeout(() => {
    const detail = document.getElementById('startup-detail');
    if (detail && !appRoot.querySelector('.dashboard, .setup-page')) {
      detail.textContent = 'Lokale Daten werden geladen. Langsame KI-Provider blockieren den Start nicht mehr.';
    }
  }, 1800);

  window.setTimeout(finish, 30000);
})();
