# MAIL-AGENT

MAIL-AGENT is a local-first AI agent deliberately restricted to email workflows.
It is not a general-purpose shell or browser agent: models can only propose structured mail actions,
and the local gateway decides whether those actions are allowed, require human approval, or are denied.

## v0.2 mailbox runtime

- Local FastAPI gateway on port `8765`
- Separate public-identity registry service on port `8770`
- Mandatory Ed25519 installation identity bound to an owner
- AES-256-GCM encrypted local credential vault for mailbox secrets
- Background IMAP sync using stable UIDs and `BODY.PEEK[]`
- Local SQLite inbox, thread index, sync cursor, and approval queue
- Provider abstraction with Ollama and Codex CLI adapters
- Observer, Assistant, Copilot, and Autonomous policy modes
- Dependency-free local onboarding and post-onboarding Control Center
- Manual sync, local inbox preview, and approval/rejection UI
- Structured mail-analysis core with code-level policy enforcement
- Local append-only audit event log

## Security model

The LLM never receives direct SMTP, IMAP, filesystem, credential-vault, or shell capabilities.
It produces a typed `MailActionProposal`; only the gateway can evaluate and later execute an action.
High-impact actions such as sending, forwarding, and deletion remain human approval-gated in v0.2.

Mailbox passwords are encrypted at rest using AES-256-GCM and are not written to `state.json` or the
mail SQLite database. The vault master key is kept in a separate permission-restricted local file.
The vault master key is wrapped by the available OS credential facility where supported, with a
permission-restricted local fallback for environments without a native secret store.

The agent's private Ed25519 key is generated locally and never sent to the registry. Only the public
key, fingerprint, owner, and installation metadata are registered remotely.

## Installation for normal users

**Windows:** download `Mail-Agent-Setup.exe`, double-click it, install, and launch MAIL-AGENT from
the Start menu. No Python, terminal, Git, Docker, or manual port configuration is required.

The desktop launcher starts the local services and opens the onboarding automatically. See
[`docs/INSTALLATION.md`](docs/INSTALLATION.md) for distribution details.

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'

uvicorn mail_agent_registry.main:app --app-dir apps/registry --port 8770 --reload
uvicorn mail_agent_gateway.main:app --app-dir apps/gateway --port 8765 --reload
```

Open `http://127.0.0.1:8765`. The UI has no Node/npm runtime dependency.

### Tests

```bash
pytest
```

## LLM providers

### Ollama

MAIL-AGENT uses the local Ollama HTTP API. Default URL: `http://127.0.0.1:11434`.
The onboarding UI probes the instance and lists installed models.

### Codex / ChatGPT sign-in

The Codex adapter does not scrape ChatGPT sessions and does not request raw browser cookies.
It delegates authentication to a locally installed Codex CLI and its own ChatGPT sign-in state.

## Local data layout

Inside `MAIL_AGENT_DATA_DIR` the gateway maintains:

```text
identity/           Ed25519 installation identity
state.json          non-secret configuration
mail.db             local inbox, thread/sync index, approval queue
audit.jsonl         append-only local audit events
secrets.vault       AES-GCM encrypted mailbox secrets
vault.key           local vault master key (permission restricted)
```

No mailbox password is stored in `state.json` or `mail.db`.

## Repository layout

```text
apps/
  gateway/        local control plane, vault, sync, storage and API
  registry/       owner/agent public identity registry
  web/            onboarding and Control Center UI
packages/
  agent_core/     identity, policy, model contracts and provider interfaces
connectors/
  imap/           IMAP/SMTP primitives
docs/
  ARCHITECTURE.md
  SECURITY.md
  ROADMAP.md
```

## v0.2 API highlights

- `POST /v1/mailboxes/probe` — validate mailbox and vault its password
- `GET /v1/mailboxes` — safe mailbox metadata + sync status
- `POST /v1/sync/run` — manual IMAP UID sync
- `GET /v1/mailboxes/{id}/messages` — local inbox
- `GET /v1/drafts` — locally persisted model-generated drafts
- `GET /v1/approvals` — persistent human approval queue
- `POST /v1/approvals/{id}/approve` / `reject` — human decision boundary
- `POST /v1/agent/analyze` — model proposal + policy evaluation + automatic approval enqueue

## Next v0.2.x work

Gmail OAuth is integrated through the Gmail API. Microsoft 365/Outlook OAuth is the next connector
layer. The local encrypted vault, mail store, sync service, and approval queue remain connector-neutral.

## Desktop experience

MAIL-AGENT is designed as a background desktop agent, not a terminal service. The Windows build starts the local gateway and registry, opens the UI, and remains available through a system-tray icon. From the tray the user can reopen MAIL-AGENT, check for updates, or stop the agent cleanly.

Gmail onboarding is intentionally one-click for end users: **Mit Google anmelden** opens the system browser, Google handles account selection and consent, and the browser returns to MAIL-AGENT automatically. OAuth client registration is a publisher/build concern and is never exposed as an end-user form.

Installed builds update from a release feed rather than requiring Git or a source checkout. When a newer Windows installer is available, MAIL-AGENT can download it, launch the installer, shut down its local services, and restart through the installer flow. Private development feeds may require an authenticated/public distribution endpoint; production users are never expected to configure GitHub credentials.
