(() => {
  const appRoot = document.getElementById('app');
  if (!appRoot) return;

  const BACKGROUND_WAIT_MS = 6000;
  const SILENT_REFRESH_TTL_MS = 60000;
  const BOOTSTRAP_TIMEOUT_MS = 5000;
  let runtimeTask = null;
  let systemHealthTask = null;
  let runtimeLastStartedAt = 0;
  let systemHealthLastStartedAt = 0;
  let bootstrapRescueInFlight = false;

  const timeout = ms => new Promise(resolve => window.setTimeout(resolve, ms));
  const htmlEscape = value => String(value || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);

  async function fetchJsonWithTimeout(path, timeoutMs = BOOTSTRAP_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' },
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      return data;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function backgroundLoader(original, taskName) {
    return function nonBlockingLoader(silent = false) {
      const isRuntime = taskName === 'runtime';
      let task = isRuntime ? runtimeTask : systemHealthTask;
      const lastStartedAt = isRuntime ? runtimeLastStartedAt : systemHealthLastStartedAt;
      const now = Date.now();

      if (silent && !task && lastStartedAt && now - lastStartedAt < SILENT_REFRESH_TTL_MS) {
        return Promise.resolve();
      }

      if (!task) {
        if (isRuntime) runtimeLastStartedAt = now;
        else systemHealthLastStartedAt = now;
        task = Promise.resolve()
          .then(() => original(true))
          .catch(() => undefined)
          .finally(() => {
            if (isRuntime) runtimeTask = null;
            else systemHealthTask = null;
          });
        if (isRuntime) runtimeTask = task;
        else systemHealthTask = task;
      }

      if (silent) return Promise.resolve();
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

  function hydrateBootstrapStatus(status) {
    try {
      if (status.identity) {
        identity = status.identity;
        form.ownerId = status.identity.owner_id || '';
        form.agentName = status.identity.agent_name || 'Nova';
        form.usageType = status.identity.usage_type || 'private';
      }

      const mailbox = status.mailboxes?.[0] || status.mailbox;
      if (mailbox) {
        mailboxConnected = true;
        mailboxId = mailbox.mailbox_id || null;
        mailboxConnector = mailbox.connector || 'imap';
        form.emailAddress = mailbox.email_address || '';
        form.mailboxUsername = mailbox.username || '';
        form.imapHost = mailbox.imap_host || '';
        form.imapPort = mailbox.imap_port || 993;
        form.smtpHost = mailbox.smtp_host || '';
        form.smtpPort = mailbox.smtp_port || 465;
      }

      if (status.configuration) {
        const config = status.configuration;
        const profile = config.profile || {};
        form.provider = config.provider || form.provider;
        form.model = config.model || form.model;
        form.autonomy = profile.autonomy_mode || form.autonomy;
        form.language = profile.language || form.language;
        form.tone = profile.tone || form.tone;
        form.emailSignature = profile.email_signature || '';
      }

      installed = !!status.completed;
    } catch (_) {
      // If a future status payload changes, rendering with safe defaults is still preferable
      // to an endless startup screen.
    }
  }

  function showBootstrapFailure(error) {
    const message = error?.name === 'AbortError'
      ? 'Der lokale Statusdienst hat innerhalb von 5 Sekunden nicht geantwortet.'
      : `Der lokale Status konnte nicht geladen werden: ${error?.message || 'Unbekannter Fehler'}`;

    appRoot.innerHTML = `
      <main style="min-height:100vh;display:grid;place-items:center;padding:32px;color:#edf3ff;font-family:Segoe UI,system-ui,sans-serif">
        <section style="width:min(580px,calc(100% - 32px));padding:30px;border:1px solid #563449;border-radius:22px;background:#0d1726;box-shadow:0 30px 80px #0008">
          <div style="font-size:22px;font-weight:700;letter-spacing:.08em">MAIL · AGENT</div>
          <h2 style="margin:20px 0 8px;font-size:20px">Start konnte nicht abgeschlossen werden</h2>
          <p style="margin:0;color:#b8c5da;line-height:1.6">${htmlEscape(message)}</p>
          <p style="margin:10px 0 0;color:#91a4c2;line-height:1.55">Du musst nicht weiter warten. Starte die Prüfung erneut oder öffne den lokalen Status separat.</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:22px">
            <button id="startup-retry" type="button" style="border:0;border-radius:10px;padding:11px 16px;font-weight:700;cursor:pointer">Erneut versuchen</button>
            <button id="startup-open-status" type="button" style="border:1px solid #38506f;border-radius:10px;padding:11px 16px;background:#132238;color:#edf3ff;font-weight:700;cursor:pointer">Lokalen Status öffnen</button>
          </div>
        </section>
      </main>`;
    document.getElementById('startup-retry')?.addEventListener('click', () => window.location.reload());
    document.getElementById('startup-open-status')?.addEventListener('click', () => {
      window.open('/v1/onboarding/status', '_blank', 'noopener');
    });
    finish();
  }

  async function rescueBootstrap() {
    if (bootstrapRescueInFlight || appRoot.querySelector('.dashboard, .setup-page')) return;
    bootstrapRescueInFlight = true;
    const detail = document.getElementById('startup-detail');
    if (detail) detail.textContent = 'Lokaler Status wird geprüft …';

    try {
      const status = await fetchJsonWithTimeout('/v1/onboarding/status');
      if (appRoot.querySelector('.dashboard, .setup-page')) return;
      hydrateBootstrapStatus(status);
      if (typeof render !== 'function') throw new Error('Oberfläche konnte nicht initialisiert werden');
      render();
      finish();

      // OAuth availability is optional bootstrap enrichment and must never hold the UI hostage.
      fetchJsonWithTimeout('/v1/oauth/providers', 2500)
        .then(oauth => {
          try {
            oauthProviders = oauth || oauthProviders;
            if (!installed && typeof render === 'function') render();
          } catch (_) {}
        })
        .catch(() => undefined);
    } catch (error) {
      if (!appRoot.querySelector('.dashboard, .setup-page')) showBootstrapFailure(error);
    } finally {
      bootstrapRescueInFlight = false;
    }
  }

  const renderTimer = window.setInterval(() => {
    if (appRoot.querySelector('.dashboard, .setup-page')) {
      finish();
      return;
    }
    try {
      if (typeof installed !== 'undefined' && installed === true && typeof render === 'function') {
        render();
        finish();
      }
    } catch (_) {
      // The independent status rescue below still has a hard timeout and visible failure state.
    }
  }, 50);

  window.setTimeout(rescueBootstrap, 150);
  window.setTimeout(() => {
    if (!appRoot.querySelector('.dashboard, .setup-page') && !bootstrapRescueInFlight) {
      rescueBootstrap();
    }
  }, 6500);
})();
