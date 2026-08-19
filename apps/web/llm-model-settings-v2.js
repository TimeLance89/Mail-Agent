(() => {
  const PROBE_URL = '/v1/providers/probe';
  const CACHE_TTL_MS = 30_000;
  const cache = new Map();
  const inFlight = new Map();

  const app = document.getElementById('app');
  const providerName = provider => provider === 'ollama' ? 'Ollama' : 'ChatGPT / Codex';
  const setupProvider = () =>
    document.querySelector('[data-choice-group="provider"].selected')?.dataset.choice || null;
  const unique = values => [...new Set((values || []).map(value => String(value).trim()).filter(Boolean))];
  const normalizeModels = (provider, models) => unique([
    ...(provider === 'codex' ? ['default'] : []),
    ...(models || []),
  ]);
  const visibleCount = (provider, models) =>
    normalizeModels(provider, models).filter(model => !(provider === 'codex' && model === 'default')).length;
  const modelLabel = (provider, model) =>
    provider === 'codex' && model === 'default' ? 'Automatisch (Codex-Standard)' : model;

  async function discover(provider, force = false) {
    const cached = cache.get(provider);
    if (!force && cached && Date.now() - cached.at < CACHE_TTL_MS) return cached.result;
    if (!force && inFlight.has(provider)) return inFlight.get(provider);

    const job = (async () => {
      const response = await fetch(PROBE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || `Provider-Prüfung fehlgeschlagen (${response.status})`);
      }
      const result = { ...data, models: normalizeModels(provider, data.models || []) };
      if (provider === 'ollama' && result.available && result.models.length === 0) {
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
  }

  function ensureNote(container, beforeSelector = null) {
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
  }

  function setNote(container, text, beforeSelector = null) {
    const note = ensureNote(container, beforeSelector);
    if (note && note.textContent !== text) note.textContent = text;
  }

  function ensureHelp(label, text) {
    if (!label) return;
    let help = label.querySelector('[data-llm-model-help]');
    if (!help) {
      help = document.createElement('small');
      help.dataset.llmModelHelp = '1';
      help.className = 'muted';
      label.appendChild(help);
    }
    if (help.textContent !== text) help.textContent = text;
  }

  function addManualFallback(label, select, provider, onApply) {
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
  }

  function createModelSelect(control, provider, models, selectedValue, id) {
    const values = normalizeModels(provider, models);
    const selected = String(selectedValue || '').trim();
    const wasDetected = !selected || values.includes(selected);
    if (selected && !values.includes(selected)) values.push(selected);

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
      if (selected && value === selected && !wasDetected) {
        option.textContent = `${value} · gespeichert, aktuell nicht erkannt`;
      }
      select.appendChild(option);
    }

    select.value = selected && values.includes(selected)
      ? selected
      : provider === 'codex' && values.includes('default')
        ? 'default'
        : values[0];
    return select;
  }

  function summary(provider, result, selected) {
    const count = visibleCount(provider, result.models || []);
    const countText = count === 1 ? '1 Modell automatisch erkannt' : `${count} Modelle automatisch erkannt`;
    return `${countText} · Ausgewählt: ${modelLabel(provider, selected || 'default')}`;
  }

  function applySettings(provider, result) {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || providerSelect.value !== provider || !control) return;

    const panel = providerSelect.closest('.panel');
    const label = control.closest('.field');
    if (!panel || !label) return;

    let selected = control.value;
    try {
      selected = selected || (typeof runtimeSettings !== 'undefined' ? runtimeSettings?.model : '');
    } catch (_) {}

    const select = createModelSelect(control, provider, result.models || [], selected, 'settings-model');
    select.dataset.llmAutoModels = provider;

    const heading = label.querySelector(':scope > span');
    if (heading && heading.textContent !== 'LLM-Modell') heading.textContent = 'LLM-Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'Installierte Ollama-Modelle werden automatisch erkannt. Du musst nur auswählen.'
        : 'Verfügbare Modelle werden automatisch aus dem offiziellen Codex-Client gelesen. „Automatisch“ nutzt dessen Standardmodell.',
    );
    addManualFallback(label, select, provider, () => setNote(panel, summary(provider, result, select.value)));

    select.onchange = () => setNote(panel, summary(provider, result, select.value));
    setNote(
      panel,
      result.available
        ? summary(provider, result, select.value)
        : (result.detail || `${providerName(provider)} ist momentan nicht bereit.`),
    );
  }

  function ensureRefreshButton(panel, provider) {
    if (!panel) return;
    let button = panel.querySelector('#settings-refresh-models');
    if (!button) {
      const actions = panel.querySelector('.inline-actions.left');
      if (!actions) return;
      button = document.createElement('button');
      button.type = 'button';
      button.id = 'settings-refresh-models';
      button.className = 'btn secondary';
      button.textContent = 'Modelle neu erkennen';
      actions.insertBefore(button, actions.firstChild);
    }
    button.dataset.provider = provider;
    button.onclick = async event => {
      event.preventDefault();
      event.stopPropagation();
      const activeProvider = document.getElementById('settings-provider')?.value || provider;
      const currentPanel = document.getElementById('settings-provider')?.closest('.panel');
      button.disabled = true;
      const previous = button.textContent;
      button.textContent = 'Ermittle Modelle …';
      setNote(currentPanel, `Verfügbare ${providerName(activeProvider)}-Modelle werden ermittelt …`);
      try {
        const result = await discover(activeProvider, true);
        applySettings(activeProvider, result);
      } catch (error) {
        setNote(currentPanel, error?.message || 'Modelle konnten nicht ermittelt werden.');
      } finally {
        button.disabled = false;
        button.textContent = previous;
      }
    };
  }

  async function enhanceSettings() {
    const providerSelect = document.getElementById('settings-provider');
    const control = document.getElementById('settings-model');
    if (!providerSelect || !control) return;

    const provider = providerSelect.value || 'ollama';
    const panel = providerSelect.closest('.panel');
    ensureRefreshButton(panel, provider);

    if (control.dataset.llmAutoModels === provider) return;
    control.dataset.llmAutoModels = `loading:${provider}`;
    setNote(panel, `Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`);

    try {
      const result = await discover(provider);
      applySettings(provider, result);
    } catch (error) {
      const latest = document.getElementById('settings-model');
      if (latest) latest.dataset.llmAutoModels = '';
      setNote(panel, error?.message || 'Modelle konnten nicht automatisch ermittelt werden.');
    }
  }

  async function enhanceOnboarding() {
    const provider = setupProvider();
    if (!provider) return;

    const card = document.querySelector('.setup-card');
    if (!card) return;

    const control = document.getElementById('model-select');
    if (control?.dataset.llmAutoModels === provider) return;

    const cached = cache.get(provider);
    if (!control && cached?.result) return;

    if (!control) {
      setNote(card, `Verfügbare ${providerName(provider)}-Modelle werden automatisch ermittelt …`, '.setup-actions');
      try {
        const result = await discover(provider);
        if (setupProvider() !== provider) return;
        try {
          if (typeof probe !== 'undefined') probe = result;
          if (typeof form !== 'undefined') {
            const current = String(form.model || '').trim();
            const models = result.models || [];
            if (!current || !models.includes(current)) {
              form.model = provider === 'codex' && models.includes('default') ? 'default' : (models[0] || '');
            }
          }
          if (typeof render === 'function') render();
        } catch (_) {}
      } catch (error) {
        setNote(card, error?.message || 'Modelle konnten nicht automatisch ermittelt werden.', '.setup-actions');
      }
      return;
    }

    const result = cached?.result || {
      available: true,
      models: [...control.options].map(option => option.value).filter(Boolean),
    };
    const label = control.closest('.field');
    if (!label) return;

    const current = control.value;
    const select = createModelSelect(control, provider, result.models || [], current, 'model-select');
    select.dataset.llmAutoModels = provider;

    const heading = label.querySelector(':scope > span');
    if (heading && heading.textContent !== 'Verfügbares Modell') heading.textContent = 'Verfügbares Modell';
    ensureHelp(
      label,
      provider === 'ollama'
        ? 'Installierte Ollama-Modelle wurden automatisch gefunden. Wähle einfach eines aus.'
        : 'Die Modellliste wurde automatisch aus dem offiziellen Codex-Client geladen. „Automatisch“ ist die bequemste Standardwahl.',
    );
    addManualFallback(label, select, provider, value => {
      try { if (typeof form !== 'undefined') form.model = value; } catch (_) {}
    });
    select.onchange = () => {
      try { if (typeof form !== 'undefined') form.model = select.value; } catch (_) {}
      setNote(card, summary(provider, result, select.value), '.setup-actions');
    };
    setNote(
      card,
      result.available
        ? summary(provider, result, select.value)
        : (result.detail || `${providerName(provider)} ist momentan nicht bereit.`),
      '.setup-actions',
    );
  }

  function enhance() {
    enhanceSettings();
    enhanceOnboarding();
  }

  enhance();

  // app.js renders complete views by replacing direct children of #app.
  // Observe only those top-level renders. Never observe the subtree, otherwise
  // the model enhancer can react to its own DOM changes and lock up the browser.
  if (app) {
    const observer = new MutationObserver(() => queueMicrotask(enhance));
    observer.observe(app, { childList: true });
  }
})();