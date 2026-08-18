# MAIL-AGENT

MAIL-AGENT is a local-first AI agent that is deliberately restricted to email workflows.
It is not a general-purpose shell or browser agent: models can only propose structured mail actions,
and a policy engine decides whether those actions are allowed, require approval, or are denied.

## v0.1 foundation

- Local FastAPI gateway on port `8765`
- Separate agent registry service on port `8770`
- Mandatory Ed25519 installation identity
- Owner-to-agent registration without uploading mailbox credentials or mail contents
- Provider abstraction with Ollama and Codex CLI adapters
- Mail-action policy engine with Observer, Assistant, Copilot, and Autonomous modes
- Dependency-free local onboarding UI served directly by the gateway
- Local IMAP/SMTP connection probe and connector primitives
- Structured mail-analysis core with code-level policy enforcement
- Local append-only audit event log

## Security model

The LLM never receives direct SMTP, IMAP, filesystem, or shell capabilities. It produces a typed
`MailActionProposal`; only the gateway may execute an action after policy evaluation. The agent's
private Ed25519 key is generated locally and never sent to the registry. Only the public key,
fingerprint, and owner/installation metadata are registered.

## Development

### Backend

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'

uvicorn mail_agent_registry.main:app --app-dir apps/registry --port 8770 --reload
uvicorn mail_agent_gateway.main:app --app-dir apps/gateway --port 8765 --reload
```

### Web UI

The onboarding UI is served directly by the gateway with no Node/npm runtime dependency.
Open `http://127.0.0.1:8765`.

### Tests

```bash
pytest
```

## LLM providers

### Ollama

MAIL-AGENT uses the local Ollama HTTP API. Default URL: `http://127.0.0.1:11434`.
The onboarding UI can probe the instance and list installed models.

### Codex / ChatGPT sign-in

The Codex adapter intentionally does not scrape ChatGPT web sessions and does not ask users for a
raw ChatGPT cookie. It detects a locally installed `codex` CLI and delegates authentication to that
official client. This is the initial path for users who want to use their eligible ChatGPT plan
without manually configuring an OpenAI API key.

## Repository layout

```text
apps/
  gateway/        local control plane and API
  registry/       owner/agent public identity registry
  web/            onboarding and management UI
packages/
  agent_core/     identity, policy, model contracts and provider interfaces
connectors/
  imap/           IMAP/SMTP primitives
docs/
  ARCHITECTURE.md
  SECURITY.md
  ROADMAP.md
```

## Current scope

This first commit establishes the trusted core and onboarding path. Message synchronization,
OAuth mailbox providers, background queues, production PostgreSQL registry storage, installers,
and autonomous execution are deliberately staged behind this foundation.
