(() => {
  const PROBE_URL = '/v1/providers/probe';
  const CACHE_TTL_MS = 30_000;
  const cache = new Map();
  const inFlight = new Map();
  let setupDiscoveryProvider = null;
  let settingsDiscoveryProvider = null;

  const providerName = provider => provider === 'ollama' ? 'Ollama' : 'ChatGPT / Codex';
  const setupProvider = () =>
    document.querySelector('[data-choice-group="provider"].selected')?.dataset.choice || null;
  const unique = values => [...new Set((values || []).map(value => String(value).trim()).filter(Boolean))];
  const actualModels = (provider, models) =>
    unique(models).filter(model => !(provider === 'codex' && model === 'default'));
  const selectableModels = (provider, models) => unique([
    ...(provider === 'codex' ? ['default'] : []),
    ...models,
  ]);
  const modelLabel = (provider, model) =>
    provider === 'codex' && model === 'default' ? 'Automatisch (Codex-Standard)' : model;

  const probeProvider = async provider => {
    const response = await fetch(PROBE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Provider-Prüfung fehlgeschlagen (${response.status})`);
    const models = selectableModels(provider, data.models || []);
    const result = { ...data, models };
    if (provider === 'ollama' && result.available && models.length === 0) {
      result.available = false;
      result.detail = 'Ollama läuft, aber es ist noch kein Modell installiert.';
    }
    return result;
  };

  const discoverModels = async (provider, force = false) => {
    const cached = cache.get(provider);
    if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.result;
    if (!force && inFlight.has(provider)) return inFlight.get(provider);
    const job = probeProvider(provider).then(result => {
      cache.set(provider, { at: Date.now(), result });
      return result;
    });
    inFlight.set(provider, job);
    try {
      return await job;
    } finally {
      if (inFlight.get(provider) === job) inFlight.delete(provider);
    }
  };

  const ensureNote = (container, beforeSelector = null) => {
    if (!container) return null;
    let note = container.querySelector('[data-llm-model-note]');
    if (!note) {
      note = document.createElement('div');
      note.dataset.llmModelNote = '1';
      note.className = 'security-note';
      const before = beforeSelector ? container.querySelector(beforeSelector) : null;
      if (before) before.insertAdjacentElement('beforebegin', note);
      else container.appendChild(note);
    }
    return note;
  };

  const setNote = (container, text, beforeSelector = null) => {
    const note = ensureNote(container, beforeSelector);
    if (note) note.textContent = text;
  };

  const ensureHelp = (label, text) => {
    if (!label) return;
    let help = label.querySelector('[data-llm-model-help]');
    if (!help) {
      help = document.createElement('small');
      help.dataset.llmModelHelp = '1';
      help.className = 'muted';
      label.appendChild(help);
    }
    help.textContent = text;
  };

  const buildSelect = (control, provider, models, savedValue, id) => {
    const values = selectableModels(provider, models);
    const saved = String(savedValue || '').trim();
    const savedDetected = !saved || values.includes(saved);
    if (saved && !values.includes(saved)) values.push(saved);

    let select = control;
    if (control.tagName !== 'SELECT') {
      select = document.createElement('select');
      control.replaceWith(select);
    }
    select.id = id;
    select.replaceChildren();

    if (!values.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Keine Modelle gefunden';
      option.disabled = true;
      option.selected = true;
      select.appendChild(option);
      return select;
    }

    for (const value of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = modelLabel(provider, value);
      if (saved && value === saved && !savedDetected) {
        option.textContent = `${value} · gespeichert, aktuell nicht erkannt`;
      }
      select.appendChild(option);
    }

    const preferred = saved && values.includes(saved)
      ? saved
      : provider === 'codex' && values.includes('default')
        ? 'default'
        : values[0];
    select.value = preferred;
    return select;
  };

  const addManualFallback = (label, select, provider, onApply) => {
    if (!label || !select || label.querySelector('[data-llm-model-manual]')) return;
    const details = document.createElement('details');
    details.dataset.llmModelManual = '1';
    details.className = 'llm-model-manual';
    const summary = document.createElement('summary');
    summary.textContent = 'Expertenoption: andere Modell-ID';
    const row = document.createElement('div');
    row.className = 'inline-actions left';
    const input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = provider === 'ollama' ? 'Eigene Ollama-Modell-ID' : 'Exakte Codex-Modell-ID';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn secondary compact';
    button.textContent = 'Übernehmen';
    button.onclick = event => {
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
    };
    row.append(input, button);
    details.append(summary, row);
    label.appendChild(details);
  };

  const resultSummary = (provider, result, selected) => {
    const count = actualModels(provider, result.models || []).length;
    const countText = count === 1 ? '1 Modell automatisch erkannt' : `${count} Modelle automatisch erkannt`;
    return `${countText} · Ausgewählt: ${modelLabel(provider, selected || 'default')}`;
  };

  const applySettings = (provider, result) => {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || providerSelect.value !== provider || !control) return;
    const label = control.closest('.field');
    const panel = providerSelect.closest('.panel');
    if (!label || !panel) return;

    let stored = control.value;
    try {
      stored = stored || (typeof runtimeSettings !== 'undefined' ? runtimeSettings?.model : '');
    } catch (_) {}

    const select = buildSelect(control, provider, result.models || [], stored, 'settings-model');
    select.dataset.llmReady = provider;
    const heading = label.querySelector(':scope > span');
    if (heading) heading.textContent = 'LLM-Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'Installierte Ollama-Modelle werden automatisch erkannt und hier angezeigt.'
        : 'Die Modellliste wird automatisch aus deinem installierten offiziellen Codex-Client gelesen. „Automatisch“ nutzt dessen Standardwahl.',
    );
    addManualFallback(label, select, provider, () => {
      setNote(panel, resultSummary(provider, result, select.value));
    });
    select.onchange = () => setNote(panel, resultSummary(provider, result, select.value));
    setNote(
      panel,
      result.available
        ? resultSummary(provider, result, select.value)
        : (result.detail || `${providerName(provider)} ist momentan nicht bereit.`),
    );
  };

  const refreshSettings = async (provider, button) => {
    const panel = document.getElementById('settings-provider')?.closest('.panel');
    if (!panel) return;
    button.disabled = true;
    const previous = button.textContent;
    button.textContent = 'Ermittle Modelle …';
    setNote(panel, `Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);
    try {
      const result = await discoverModels(provider, true);
      applySettings(provider, result);
    } catch (error) {
      setNote(panel, error?.message || 'Modelle konnten nicht ermittelt werden.');
    } finally {
      button.disabled = false;
      button.textContent = previous;
    }
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
    button.onclick = event => {
      event.preventDefault();
      event.stopPropagation();
      refreshSettings(provider, button);
    };
  };

  const autoDiscoverSettings = async provider => {
    settingsDiscoveryProvider = provider;
    const panel = document.getElementById('settings-provider')?.closest('.panel');
    if (panel) setNote(panel, `Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);
    try {
      const result = await discoverModels(provider);
      applySettings(provider, result);
    } catch (error) {
      if (panel) setNote(panel, error?.message || 'Modelle konnten nicht automatisch ermittelt werden.');
    }
  };

  const enhanceSettings = () => {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || !control) return;
    const provider = providerSelect.value || 'ollama';
    const panel = providerSelect.closest('.panel');
    ensureRefreshButton(panel, provider);
    if (control.dataset.llmReady === provider) return;

    const cached = cache.get(provider);
    if (cached && Date.now() - cached.at < CACHE_TTL_MS) {
      applySettings(provider, cached.result);
      return;
    }
    if (settingsDiscoveryProvider !== provider || !inFlight.has(provider)) {
      autoDiscoverSettings(provider);
    }
  };

  const setSetupNote = text => {
    const card = document.querySelector('.setup-card');
    if (card) setNote(card, text, '.setup-actions');
  };

  const applySetupProbe = (provider, result) => {
    if (setupProvider() !== provider) return;
    try {
      if (typeof probe !== 'undefined') probe = result;
      if (typeof form !== 'undefined') {
        const models = result.models || [];
        const current = String(form.model || '').trim();
        if (!current || !models.includes(current)) {
          form.model = provider === 'codex' && models.includes('default') ? 'default' : (models[0] || '');
        }
      }
      if (typeof render === 'function') render();
    } catch (_) {}
  };

  const autoDiscoverSetup = async provider => {
    if (setupDiscoveryProvider === provider) return;
    setupDiscoveryProvider = provider;
    setSetupNote(`Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);
    try {
      const result = await discoverModels(provider);
      applySetupProbe(provider, result);
    } catch (error) {
      setupDiscoveryProvider = null;
      setSetupNote(error?.message || 'Modelle konnten nicht automatisch ermittelt werden.');
    }
  };

  const enhanceOnboarding = () => {
    const provider = setupProvider();
    if (!provider) {
      setupDiscoveryProvider = null;
      return;
    }

    const control = document.getElementById('model-select');
    const cached = cache.get(provider);
    if (!control) {
      if (cached?.result && !cached.result.available) {
        setSetupNote(cached.result.detail || `${providerName(provider)} ist momentan nicht bereit.`);
      } else {
        autoDiscoverSetup(provider);
      }
      return;
    }
    if (control.dataset.llmReady === provider) return;

    const label = control.closest('.field');
    const card = control.closest('.setup-card');
    if (!label || !card) return;
    const result = cached?.result || {
      available: true,
      models: [...control.options].map(option => option.value).filter(Boolean),
    };
    let stored = control.value;
    try { stored = stored || (typeof form !== 'undefined' ? form.model : ''); } catch (_) {}
    const select = buildSelect(control, provider, result.models || [], stored, 'model-select');
    select.dataset.llmReady = provider;
    const heading = label.querySelector(':scope > span');
    if (heading) heading.textContent = 'Verfügbares Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'MAIL-AGENT hat die installierten Ollama-Modelle automatisch gefunden. Du musst nur auswählen.'
        : 'MAIL-AGENT hat die Modelle des offiziellen Codex-Clients automatisch ermittelt. „Automatisch“ ist die bequemste Standardwahl.',
    );
    addManualFallback(label, select, provider, value => {
      try { if (typeof form !== 'undefined') form.model = value; } catch (_) {}
    });
    select.onchange = () => {
      try { if (typeof form !== 'undefined') form.model = select.value; } catch (_) {}
      setSetupNote(resultSummary(provider, result, select.value));
    };
    setSetupNote(
      result.available
        ? resultSummary(provider, result, select.value)
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
