(() => {
  const PROBE_URL = '/v1/providers/probe';
  const MODEL_HELP_ATTR = 'data-llm-model-help';
  const MODEL_NOTE_ATTR = 'data-llm-model-note';

  const providerName = provider => provider === 'ollama' ? 'Ollama' : 'ChatGPT / Codex';

  const selectedSetupProvider = () =>
    document.querySelector('[data-choice-group="provider"].selected')?.dataset.choice || null;

  const modelSuggestions = control => {
    if (!control) return [];
    if (control.tagName === 'SELECT') {
      return [...control.options].map(option => option.value).filter(Boolean);
    }
    const listId = control.getAttribute('list');
    const list = listId ? document.getElementById(listId) : null;
    return list ? [...list.options].map(option => option.value).filter(Boolean) : [];
  };

  const ensureDatalist = (control, id, suggestions) => {
    let datalist = document.getElementById(id);
    if (!datalist) {
      datalist = document.createElement('datalist');
      datalist.id = id;
      control.insertAdjacentElement('afterend', datalist);
    }
    const values = [...new Set((suggestions || []).map(value => String(value).trim()).filter(Boolean))];
    datalist.replaceChildren(...values.map(value => {
      const option = document.createElement('option');
      option.value = value;
      return option;
    }));
    control.setAttribute('list', id);
    return datalist;
  };

  const asModelInput = (control, { id, listId, suggestions, placeholder }) => {
    if (!control) return null;
    const currentValue = String(control.value || '').trim();
    let input = control;
    if (control.tagName !== 'INPUT') {
      input = document.createElement('input');
      input.id = id;
      input.value = currentValue;
      control.replaceWith(input);
    }
    input.id = id;
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = placeholder;
    ensureDatalist(input, listId, suggestions);
    return input;
  };

  const addHelp = (label, text) => {
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

  const addSelectionNote = (panel, provider, input) => {
    if (!panel || !input) return;
    let note = panel.querySelector(`[${MODEL_NOTE_ATTR}]`);
    if (!note) {
      note = document.createElement('div');
      note.setAttribute(MODEL_NOTE_ATTR, '1');
      note.className = 'security-note';
      const formGrid = panel.querySelector('.form-grid');
      if (formGrid) formGrid.insertAdjacentElement('afterend', note);
    }
    const selected = String(input.value || 'default').trim() || 'default';
    note.textContent = `Ausgewähltes Modell: ${providerName(provider)} · ${selected}`;
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

  const refreshSuggestions = (input, provider, models) => {
    const current = String(input.value || '').trim();
    const suggestions = [...new Set([
      ...(provider === 'codex' ? ['default'] : []),
      ...(models || []),
      ...(current ? [current] : []),
    ])];
    ensureDatalist(input, input.getAttribute('list') || 'settings-model-options', suggestions);
  };

  const ensureRefreshButton = (panel, provider) => {
    if (!panel || panel.querySelector('#settings-refresh-models')) return;
    const actions = panel.querySelector('.inline-actions.left');
    if (!actions) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'settings-refresh-models';
    button.className = 'btn secondary';
    button.textContent = provider === 'ollama' ? 'Modelle neu laden' : 'Provider prüfen';
    button.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      const oldText = button.textContent;
      button.textContent = 'Prüfe …';
      const input = panel.querySelector('#settings-model');
      const note = panel.querySelector(`[${MODEL_NOTE_ATTR}]`);
      try {
        const result = await probeProvider(provider);
        if (input) refreshSuggestions(input, provider, result.models || []);
        if (note) {
          if (!result.available) note.textContent = result.detail || `${providerName(provider)} ist momentan nicht bereit.`;
          else if (provider === 'ollama' && (result.models || []).length) note.textContent = `${result.models.length} installierte Ollama-Modelle gefunden. Wähle das gewünschte Modell im Feld oben.`;
          else note.textContent = `${providerName(provider)} ist bereit. Trage „default“ oder eine vom Provider unterstützte Modell-ID ein.`;
        }
      } catch (error) {
        if (note) note.textContent = error?.message || 'Provider konnte nicht geprüft werden.';
      } finally {
        button.disabled = false;
        button.textContent = oldText;
      }
    });
    actions.insertBefore(button, actions.firstChild);
  };

  const enhanceSettings = () => {
    const providerSelect = document.getElementById('settings-provider');
    const originalControl = document.getElementById('settings-model');
    if (!providerSelect || !originalControl) return;
    const provider = providerSelect.value || 'ollama';
    const label = originalControl.closest('.field');
    const panel = providerSelect.closest('.panel');
    if (!label || !panel || label.dataset.llmModelEnhanced === provider) return;

    const suggestions = modelSuggestions(originalControl);
    const input = asModelInput(originalControl, {
      id: 'settings-model',
      listId: 'settings-model-options',
      suggestions: [...(provider === 'codex' ? ['default'] : []), ...suggestions],
      placeholder: provider === 'ollama' ? 'z. B. qwen3:latest' : 'default oder exakte Modell-ID',
    });
    if (!input) return;

    label.dataset.llmModelEnhanced = provider;
    const heading = label.querySelector('span');
    if (heading) heading.textContent = provider === 'ollama' ? 'LLM-Modell' : 'LLM-Modell-ID';
    addHelp(
      label,
      provider === 'ollama'
        ? 'Installierte Ollama-Modelle erscheinen als Vorschläge. Du kannst das Modell jederzeit wechseln.'
        : '„default“ überlässt die Wahl dem offiziellen Codex-Client. Alternativ kannst du eine konkrete, von deinem ChatGPT/Codex-Zugang unterstützte Modell-ID eintragen.',
    );
    addSelectionNote(panel, provider, input);
    ensureRefreshButton(panel, provider);
    input.addEventListener('input', () => addSelectionNote(panel, provider, input));
  };

  const enhanceOnboarding = () => {
    const originalControl = document.getElementById('model-select');
    if (!originalControl) return;
    const provider = selectedSetupProvider() || 'ollama';
    const label = originalControl.closest('.field');
    if (!label || label.dataset.llmModelEnhanced === provider) return;

    const suggestions = modelSuggestions(originalControl);
    const input = asModelInput(originalControl, {
      id: 'model-select',
      listId: 'setup-model-options',
      suggestions: [...(provider === 'codex' ? ['default'] : []), ...suggestions],
      placeholder: provider === 'ollama' ? 'Ollama-Modell auswählen' : 'default oder exakte Modell-ID',
    });
    if (!input) return;

    label.dataset.llmModelEnhanced = provider;
    const heading = label.querySelector('span');
    if (heading) heading.textContent = 'LLM-Modell';
    addHelp(
      label,
      provider === 'ollama'
        ? 'Die gefundenen lokalen Ollama-Modelle stehen als Vorschläge bereit.'
        : 'Mit „default“ nutzt Codex seine Standardwahl. Für ein bestimmtes Modell trägst du dessen Modell-ID direkt ein.',
    );
    input.addEventListener('input', () => {
      try {
        if (typeof form !== 'undefined') form.model = input.value.trim() || 'default';
      } catch (_) {
        // app.js remains the source of truth; saveVisible() reads the same field on navigation.
      }
    });
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