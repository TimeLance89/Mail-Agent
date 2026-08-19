(() => {
  const PROBE_URL = '/v1/providers/probe';
  const MODEL_HELP_ATTR = 'data-llm-model-help';
  const MODEL_NOTE_ATTR = 'data-llm-model-note';
  const MANUAL_ATTR = 'data-llm-model-manual';
  const DISCOVERY_TTL_MS = 30_000;

  const cache = new Map();
  const inFlight = new Map();
  let setupDiscoveryProvider = null;
  let settingsDiscoveryProvider = null;

  const providerName = provider => provider === 'ollama' ? 'Ollama' : 'ChatGPT / Codex';
  const selectedSetupProvider = () =>
    document.querySelector('[data-choice-group="provider"].selected')?.dataset.choice || null;

  const unique = values => [...new Set((values || []).map(value => String(value).trim()).filter(Boolean))];

  const modelsFor = (provider, models) => unique([
    ...(provider === 'codex' ? ['default'] : []),
    ...(models || []),
  ]);

  const modelLabel = (provider, model) => {
    if (provider === 'codex' && model === 'default') return 'Automatisch (Codex-Standard)';
    return model;
  };

  const probeProvider = async provider => {
    const response = await fetch(PROBE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Provider-Prüfung fehlgeschlagen (${response.status})`);
    return data;
  };

  const discoverModels = async (provider, { force = false } = {}) => {
    const cached = cache.get(provider);
    if (!force && cached && Date.now() - cached.at < DISCOVERY_TTL_MS) return cached.result;
    if (!force && inFlight.has(provider)) return inFlight.get(provider);

    const job = (async () => {
      const raw = await probeProvider(provider);
      const models = modelsFor(provider, raw.models || []);
      const result = { ...raw, models };
      if (provider === 'ollama' && raw.available && models.length === 0) {
        result.available = false;
        result.detail = 'Ollama läuft, aber es ist noch kein Modell installiert.';
      }
      cache.set(provider, { at: Date.now(), result });
      return result;
    })();

    inFlight.set(provider, job);
    try {
      return await job;
    } finally {
      if (inFlight.get(provider) === job) inFlight.delete(provider);
    }
  };

  const ensureHelp = (label, text) => {
    if (!label) return;
    let help = label.querySelector(`[${MODEL_HELP_ATTR}]`);
    if (!help) {
      help = document.createElement('small');
      help.setAttribute(MODEL_HELP_ATTR, '1');
      help.className = 'muted';
      label.appendChild(help);
    }
    help.textContent = text;
  };

  const ensureNote = panel => {
    if (!panel) return null;
    let note = panel.querySelector(`[${MODEL_NOTE_ATTR}]`);
    if (!note) {
      note = document.createElement('div');
      note.setAttribute(MODEL_NOTE_ATTR, '1');
      note.className = 'security-note';
      const formGrid = panel.querySelector('.form-grid');
      if (formGrid) formGrid.insertAdjacentElement('afterend', note);
      else panel.appendChild(note);
    }
    return note;
  };

  const setNote = (panel, text) => {
    const note = ensureNote(panel);
    if (note) note.textContent = text;
  };

  const currentValue = (control, fallback = '') => String(control?.value || fallback || '').trim();

  const asSelect = (control, { id, provider, models, selected }) => {
    if (!control) return null;
    const values = modelsFor(provider, models);
    const stored = String(selected || '').trim();
    const storedWasDiscovered = !stored || values.includes(stored);
    if (stored && !values.includes(stored)) values.push(stored);

    let select = control;
    if (control.tagName !== 'SELECT') {
      select = document.createElement('select');
      control.replaceWith(select);
    }
    select.id = id;
    select.removeAttribute('list');
    select.replaceChildren();

    if (!values.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = provider === 'ollama' ? 'Keine installierten Modelle gefunden' : 'Keine Modelle erkannt';
      option.disabled = true;
      option.selected = true;
      select.appendChild(option);
      return select;
    }

    values.forEach(value => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = modelLabel(provider, value);
      if (stored && value === stored && !storedWasDiscovered) {
        option.textContent = `${value} · gespeichert, aktuell nicht erkannt`;
      }
      select.appendChild(option);
    });

    const preferred = stored && values.includes(stored)
      ? stored
      : provider === 'codex' && values.includes('default')
        ? 'default'
        : values[0];
    select.value = preferred;
    return select;
  };

  const addManualFallback = (label, select, provider, onApply) => {
    if (!label || !select || label.querySelector(`[${MANUAL_ATTR}]`)) return;
    const details = document.createElement('details');
    details.setAttribute(MANUAL_ATTR, '1');
    details.className = 'llm-model-manual';

    const summary = document.createElement('summary');
    summary.textContent = 'Expertenoption: andere Modell-ID';
    const row = document.createElement('div');
    row.className = 'inline-actions left';
    const input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = provider === 'ollama' ? 'z. B. eigenes Ollama-Modell' : 'Exakte Codex-Modell-ID';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn secondary compact';
    button.textContent = 'Übernehmen';
    button.addEventListener('click', event => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) return;
      if (![...select.options].some(option => option.value === value)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = `${value} · manuell`;
        select.appendChild(option);
      }
      select.value = value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      onApply?.(value);
      details.open = false;
    });
    row.append(input, button);
    details.append(summary, row);
    label.appendChild(details);
  };

  const updateSelectionNote = (panel, provider, select, count) => {
    if (!panel || !select) return;
    const selected = currentValue(select, 'default') || 'default';
    const discovered = Math.max(0, Number(count || 0));
    const suffix = discovered === 1 ? '1 Modell automatisch erkannt' : `${discovered} Modelle automatisch erkannt`;
    setNote(panel, `${suffix} · Aktiv: ${providerName(provider)} · ${modelLabel(provider, selected)}`);
  };

  const applySettingsModels = (provider, result) => {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || providerSelect.value !== provider || !control) return;
    const label = control.closest('.field');
    const panel = providerSelect.closest('.panel');
    if (!label || !panel) return;

    const saved = currentValue(control, (() => {
      try { return typeof runtimeSettings !== 'undefined' ? runtimeSettings?.model : ''; }
      catch (_) { return ''; }
    })());
    const actualModels = provider === 'codex'
      ? (result.models || []).filter(model => model !== 'default')
      : (result.models || []);
    const select = asSelect(control, {
      id: 'settings-model',
      provider,
      models: result.models || [],
      selected: saved,
    });
    if (!select) return;

    label.dataset.llmModelEnhanced = provider;
    const heading = label.querySelector(':scope > span');
    if (heading) heading.textContent = 'LLM-Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'MAIL-AGENT erkennt installierte Ollama-Modelle automatisch. Normalerweise musst du keine Modell-ID kennen.'
        : 'MAIL-AGENT liest die verfügbaren Modelle automatisch aus dem installierten offiziellen Codex-Client. „Automatisch“ verwendet dessen Standardmodell.',
    );
    addManualFallback(label, select, provider, () => updateSelectionNote(panel, provider, select, actualModels.length));
    select.addEventListener('change', () => updateSelectionNote(panel, provider, select, actualModels.length));

    if (!result.available) setNote(panel, result.detail || `${providerName(provider)} ist momentan nicht bereit.`);
    else updateSelectionNote(panel, provider, select, actualModels.length);
  };

  const ensureRefreshButton = (panel, provider) => {
    if (!panel) return;
    let button = panel.querySelector('#settings-refresh-models');
    if (!button) {
      const actions = panel.querySelector('.inline-actions.left');
      if (!actions) return;
      button = document.createElement('button');
      button.type = 'button';
      button.id = 'settings-refresh-models';
      button.className = 'btn secondary';
      actions.insertBefore(button, actions.firstChild);
    }
    button.textContent = 'Modelle neu erkennen';
    button.onclick = async event => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      const oldText = button.textContent;
      button.textContent = 'Ermittle Modelle …';
      try {
        const result = await discoverModels(provider, { force: true });
        applySettingsModels(provider, result);
      } catch (error) {
        setNote(panel, error?.message || 'Verfügbare Modelle konnten nicht ermittelt werden.');
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    };
  };

  const autoDiscoverSettings = async provider => {
    if (settingsDiscoveryProvider === provider && inFlight.has(`settings:${provider}`)) return;
    settingsDiscoveryProvider = provider;
    const control = document.getElementById('settings-model');
    const panel = document.getElementById('settings-provider')?.closest('.panel');
    if (panel) setNote(panel, `Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);
    try {
      const result = await discoverModels(provider);
      applySettingsModels(provider, result);
    } catch (error) {
      if (panel) setNote(panel, error?.message || 'Verfügbare Modelle konnten nicht automatisch ermittelt werden.');
      if (control) control.disabled = false;
    }
  };

  const enhanceSettings = () => {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || !control) return;
    const provider = providerSelect.value || 'ollama';
    const panel = providerSelect.closest('.panel');
    ensureRefreshButton(panel, provider);

    const cached = cache.get(provider);
    if (cached && Date.now() - cached.at < DISCOVERY_TTL_MS) {
      applySettingsModels(provider, cached.result);
    } else if (settingsDiscoveryProvider !== provider || !control.dataset.llmDiscoveryStarted) {
      control.dataset.llmDiscoveryStarted = '1';
      autoDiscoverSettings(provider);
    }
  };

  const setSetupLoadingNote = text => {
    const card = document.querySelector('.setup-card');
    if (!card) return;
    let note = card.querySelector(`[${MODEL_NOTE_ATTR}]`);
    if (!note) {
      note = document.createElement('div');
      note.setAttribute(MODEL_NOTE_ATTR, '1');
      note.className = 'security-note';
      const actions = card.querySelector('.setup-actions');
      if (actions) actions.insertAdjacentElement('beforebegin', note);
      else card.appendChild(note);
    }
    note.textContent = text;
  };

  const applySetupResult = (provider, result) => {
    const currentProvider = selectedSetupProvider();
    if (currentProvider !== provider) return;
    try {
      if (typeof probe !== 'undefined') probe = result;
      if (typeof form !== 'undefined') {
        const models = result.models || [];
        const current = String(form.model || '').trim();
        if (!current || !models.includes(current)) {
          form.model = provider === 'codex' && models.includes('default')
            ? 'default'
            : (models[0] || '');
        }
      }
      if (typeof render === 'function') render();
    } catch (_) {
      // app.js remains the source of truth. The MutationObserver will retry DOM enhancement.
    }
  };

  const autoDiscoverSetup = async provider => {
    if (setupDiscoveryProvider === provider) return;
    setupDiscoveryProvider = provider;
    setSetupLoadingNote(`Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);
    try {
      const result = await discoverModels(provider);
      applySetupResult(provider, result);
    } catch (error) {
      setupDiscoveryProvider = null;
      setSetupLoadingNote(error?.message || 'Modelle konnten nicht automatisch ermittelt werden. Du kannst die Prüfung erneut starten.');
    }
  };

  const enhanceOnboarding = () => {
    const provider = selectedSetupProvider();
    if (!provider) {
      setupDiscoveryProvider = null;
      return;
    }

    const control = document.getElementById('model-select');
    if (!control) {
      autoDiscoverSetup(provider);
      return;
    }

    const label = control.closest('.field');
    const card = control.closest('.setup-card');
    if (!label || !card) return;
    const cached = cache.get(provider);
    const result = cached?.result || {
      available: true,
      models: [...control.options].map(option => option.value).filter(Boolean),
    };
    const actualModels = provider === 'codex'
      ? (result.models || []).filter(model => model !== 'default')
      : (result.models || []);
    const select = asSelect(control, {
      id: 'model-select',
      provider,
      models: result.models || [],
      selected: currentValue(control, (() => {
        try { return typeof form !== 'undefined' ? form.model : ''; }
        catch (_) { return ''; }
      })()),
    });
    if (!select) return;

    label.dataset.llmModelEnhanced = provider;
    const heading = label.querySelector(':scope > span');
    if (heading) heading.textContent = 'Verfügbares Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'Installierte Modelle wurden automatisch gefunden. Wähle einfach eines aus.'
        : 'Die Modellliste stammt automatisch aus deinem installierten Codex-Client. „Automatisch“ ist die bequemste Standardwahl.',
    );
    addManualFallback(label, select, provider, value => {
      try { if (typeof form !== 'undefined') form.model = value; } catch (_) {}
    });
    select.onchange = () => {
      try { if (typeof form !== 'undefined') form.model = select.value; } catch (_) {}
      setSetupLoadingNote(`${actualModels.length} Modelle automatisch erkannt · Ausgewählt: ${modelLabel(provider, select.value)}`);
    };
    setSetupLoadingNote(
      result.available
        ? `${actualModels.length} Modelle automatisch erkannt · Ausgewählt: ${modelLabel(provider, select.value)}`
        : (result.detail || `${providerName(provider)} ist momentan nicht bereit.`),
    );
  };

  const enhance = () => {
    enhanceSettings();
    enhanceOnboarding();
  };

  enhance();
  const app = document.getElementById('app');
  if (app) {
    const observer = new MutationObserver(() => queueMicrotask(enhance));
    observer.observe(app, { childList: true, subtree: true });
  }
})();
