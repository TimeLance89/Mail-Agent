# 0.13 Hotfix: LLM model observer freeze

The automatic LLM model selector must never observe its own subtree mutations. `app.js` renders complete views by replacing direct children of `#app`, so the selector listens only for top-level child changes.

Regression invariant:

- active UI asset: `llm-model-settings-v2.js`
- observer: `observer.observe(app, { childList: true })`
- forbidden for this selector: `subtree: true`

This prevents the model enhancer from reacting to notes, select options, helper text, or refresh-button mutations that it created itself.
