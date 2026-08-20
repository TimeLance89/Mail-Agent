# MAIL-AGENT

MAIL-AGENT is a local-first AI assistant for email workflows with an optional, separately permissioned
Google Calendar scheduling capability. It is not a general-purpose shell or browser agent: models
produce typed proposals and the local gateway decides whether an action is read-only, requires human
approval, or is denied.

## Current preview: v0.17.1

- Local FastAPI gateway on port `8765`
- Separate public-identity registry service on port `8770`
- Mandatory Ed25519 installation identity bound to an owner
- AES-256-GCM encrypted local credential vault for mailbox/OAuth secrets
- Gmail API, Microsoft Graph, and IMAP/SMTP mailbox paths
- Provider abstraction with Ollama and Codex CLI adapters
- Observer, Assistant, Copilot, and Autonomous mail-policy modes
- Persistent mail drafts, approvals, audit traces, conversation state, and owner-controlled learning
- Drafts can be explicitly discarded; an attached pending send approval is rejected atomically
- Incremental Google Calendar OAuth capability on Google mailboxes
- Calendar list, agenda, events, Free/Busy, daily briefing, and deterministic free-slot search
- Simplified Calendar Assistant focused on the user's goal and required decision rather than API controls
- Concrete appointment times from mail are checked directly against Google Free/Busy, including weekends
- Calendar Concierge for read-only questions, clarification, and typed scheduling proposals
- Mail-to-Calendar scheduling hints and availability-reply drafts
- Separate approval-gated Calendar create/update/delete/invite execution
- Calendar conflict re-checks, ETag stale-event protection, and idempotent create retries
- Actionable Google Calendar permission/API diagnostics instead of generic 401/403 messages
- Windows installer plus standalone Windows/Linux/macOS builds

## Security model

The LLM never receives direct SMTP, IMAP, Google Calendar, filesystem, credential-vault, or arbitrary
shell capabilities. Mail reasoning produces typed `MailActionProposal` values. Calendar reasoning can
only produce typed Calendar proposals or read-only answers. Gateway code remains the enforcement
point for both domains.

Sending and forwarding mail remain human approval-gated. Calendar create/update/delete operations and
attendee notifications are also always human approval-gated, including in autonomous mode. Incoming
mail is untrusted scheduling context: it can contribute factual context but cannot authorize a Calendar
mutation, invite an attendee, enable notifications, bypass approval, change policy, or modify identity.

Discarding a draft is a local owner action, not a hard delete. MAIL-AGENT keeps its audit history. If
the draft is linked to a still-pending send approval, both changes are committed atomically: the
approval becomes rejected and the draft becomes discarded. Already sent or already approved outbound
work cannot be silently discarded.

Mailbox passwords and OAuth refresh tokens are encrypted at rest and are not written to `state.json`,
the mail database, the Calendar approval database, or model-visible memory. See
[`docs/SECURITY.md`](docs/SECURITY.md) for the detailed boundaries.

## Google Calendar in 0.17.1

A user with a connected Google mailbox can choose **Google Kalender verbinden**. MAIL-AGENT performs an
incremental OAuth grant and requests the Calendar permissions it actually needs:

- `calendar.events` — read/edit event data
- `calendar.calendarlist.readonly` — list the user's calendars and access roles
- `calendar.freebusy` — query availability

Existing Gmail authorization remains a separate capability. Tokens continue to use the local encrypted
OAuth vault.

The main **Kalender** work area is intentionally task-first. The normal flow is:

1. tell MAIL-AGENT what should be checked or handled, or select a detected scheduling mail;
2. MAIL-AGENT checks the authoritative Google Calendar facts;
3. the UI shows one clear result/recommendation;
4. only a real side effect asks for an explicit owner approval.

Technical controls such as calendar selection, refresh and generic free-slot search live under
**Optionen & Details** instead of competing with the primary workflow.

When an email contains one unambiguous concrete date and time, MAIL-AGENT checks that exact interval
first. This direct Free/Busy check is independent of the generic Monday–Friday work-slot finder, so a
request such as Saturday 22.08.2026 at 16:00 is checked on Saturday rather than being replaced by Friday
alternatives. If the requested time is occupied, alternatives are searched on the same day first.

The assistant can also:

- show today's and upcoming appointments,
- answer read-only questions about the schedule,
- find real free 30/60/90-minute windows from Google Free/Busy,
- prepare a new appointment,
- prepare a move or cancellation of an existing appointment,
- add owner-authorized attendees and Google invitations,
- detect likely scheduling requests in synced email without taking action,
- use a selected email as untrusted scheduling context,
- prepare a signed email reply containing only gateway-verified free slots.

The assistant asks for clarification instead of guessing missing dates/times. A model-selected event ID
must exist in the gateway-supplied calendar context. Calendar writes are checked for access role and
conflicts when proposed and again immediately before execution.

## Calendar reliability contract

Calendar mutations use a dedicated persistent approval queue. They do not extend the model-controlled
mail action schema.

- create: deterministic Google event ID prevents duplicate appointments after a lost response/retry;
- update: the original event ETag is frozen with the proposal and revalidated before execution;
- delete: missing-after-retry is reconciled as already deleted, while changed events require refresh;
- crash recovery: interrupted Calendar executions become explicit safe-retry states;
- conflicts: existing opaque/busy events block scheduling unless the owner explicitly overrides;
- shared calendars: Google `owner`, `writer`, and `writerWithoutPrivateAccess` roles are writable;
  `reader` and `freeBusyReader` remain non-writable.

## Installation for normal users

**Windows:** download `Mail-Agent-Setup.exe`, double-click it, install, and launch MAIL-AGENT from the
Start menu. No Python, terminal, Git, Docker, or manual port configuration is required.

The desktop launcher starts the local services and opens onboarding automatically. See
[`docs/INSTALLATION.md`](docs/INSTALLATION.md) for distribution details.

## Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'

uvicorn mail_agent_registry.main:app --app-dir apps/registry --port 8770 --reload
uvicorn mail_agent_gateway.main_v171:app --app-dir apps/gateway --port 8765 --reload
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

The Codex adapter does not scrape ChatGPT sessions and does not request raw browser cookies. It
delegates authentication to a locally installed Codex CLI and its own ChatGPT sign-in state.

## Local data layout

Inside `MAIL_AGENT_DATA_DIR` the gateway maintains:

```text
identity/           Ed25519 installation identity
state.json          non-secret configuration
mail.db             local inbox, drafts and mail approval queue
calendar.db         Calendar mutation approval/recovery queue
conversations.db    local conversation/sender-pattern state
audit.jsonl         append-only local audit events
secrets.vault       AES-GCM encrypted mailbox/OAuth secrets
vault.key           local vault master key (permission restricted)
```

No mailbox password or OAuth refresh token is stored in `state.json`, `mail.db`, or `calendar.db`.

## Repository layout

```text
apps/
  gateway/        local control plane, vault, mail + Calendar services and APIs
  registry/       owner/agent public identity registry
  web/            onboarding and desktop workbench UI
packages/
  agent_core/     identity, policy, model contracts and provider interfaces
connectors/
  imap/           IMAP/SMTP primitives
  google/         Gmail + Google Calendar OAuth/API primitives
  microsoft/      Microsoft Graph mail primitives
docs/
  ARCHITECTURE.md
  SECURITY.md
  INSTALLATION.md
```

## 0.17.1 API highlights

- `POST /v1/oauth/google/calendar/start` — incremental Google Calendar OAuth
- `GET /v1/calendar/status` — Calendar capabilities without exposing credentials
- `GET /v1/calendar/calendars` / `events` — safe calendar/event reads
- `POST /v1/calendar/freebusy` — raw Google availability query
- `POST /v1/calendar/free-slots` — deterministic generic work-hour slot finder
- `GET /v1/calendar/briefing` — today + upcoming free-slot briefing
- `GET /v1/calendar/mail-suggestions` — side-effect-free scheduling hints from local mail
- `POST /v1/calendar/concierge` — exact-time check, answer, clarify, or enqueue one typed Calendar proposal
- `POST /v1/calendar/mail-reply` — signed draft with gateway-rendered verified free slots
- `GET /v1/calendar/approvals` — separate Calendar approval queue
- `POST /v1/calendar/approvals/{id}/approve` / `reject` — human Calendar decision boundary
- `POST /v1/drafts/{id}/discard` — audit-preserving owner discard; rejects a linked pending approval atomically

## Desktop experience

MAIL-AGENT is designed as a background desktop agent, not a terminal service. The Windows build starts
local services, opens the UI, and remains available through a system-tray icon. The workbench combines
mail triage, drafts, approvals, activity, settings, and the optional Calendar planning area while
preserving separate action/approval boundaries underneath.

Installed builds update from the preview release feed rather than requiring Git or a source checkout.
Updates replace program files while preserving local identity, encrypted credentials, settings, and
local databases.
