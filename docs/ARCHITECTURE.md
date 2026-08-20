# Architecture

## Trust boundaries

MAIL-AGENT 0.17 has six primary boundaries:

1. **Mailbox boundary** — IMAP/SMTP and provider OAuth credentials stay in the local encrypted vault.
2. **Local storage boundary** — mail content, Calendar approval state, conversation state, and audit data stay local.
3. **Model boundary** — the gateway decides which normalized message/calendar context is sent to the selected model.
4. **Mail action boundary** — models only return typed mail proposals; policy/approval/executor code remains authoritative.
5. **Calendar action boundary** — Calendar reads are separate from Calendar mutations; every mutation is a typed proposal in its own approval queue.
6. **Identity boundary** — the remote registry receives only public installation identity metadata.

## Runtime topology

```text
Browser UI (localhost:8765)
          |
          v
Gateway (localhost:8765)
  |       |          |             |
  |       |          |             +--> LLM provider (Ollama / Codex CLI)
  |       |          +----------------> encrypted credential vault
  |       +---------------------------> local SQLite stores
  +-----------------------------------> Registry (public identity metadata only)
          |
          +--> Mail connector (Gmail / Microsoft / IMAP+SMTP)
          |
          +--> Google Calendar API (optional capability)
```

The Windows launcher embeds the current web bundle and imports the 0.17 gateway layer after frozen
runtime paths are configured. Update restart keeps `PYINSTALLER_RESET_ENVIRONMENT=1` so stale one-file
extraction paths do not leak into the next process.

## Mail synchronization path

```text
sync scheduler / manual sync
  -> load non-secret mailbox metadata
  -> decrypt credential from vault
  -> connector read (Gmail / Microsoft / IMAP BODY.PEEK[])
  -> normalize message + thread IDs
  -> SQLite upsert
  -> advance connector cursor
  -> audit event
```

## Mail reasoning path

```text
local/incoming mail
  -> deterministic pre-LLM classification when possible
  -> normalized MailMessageContext
  -> routed LLM when required
  -> typed MailActionProposal
  -> PolicyEngine
  -> allow / require approval / deny
  -> draft or persistent mail Approval Queue
  -> human decision for high-impact actions
  -> executor
  -> audit/activity event
```

The model does not receive SMTP/IMAP/provider mutation primitives. Recipient restrictions, Agent-ID
signature, approval state, and policy are gateway-authoritative.

## Google Calendar connection path

Calendar is added as a capability to an existing Google mailbox rather than creating an unrelated
credential silo.

```text
Google mailbox connected
  -> user selects "Google Kalender verbinden"
  -> OAuth PKCE session purpose=calendar
  -> incremental consent: gmail.modify + Calendar scopes
  -> validate complete Calendar grant
  -> save refresh/access token set in encrypted OAuth vault
  -> mark mailbox capabilities: mail + calendar
```

Calendar scopes are deliberately narrower than full `calendar` access: event read/write,
CalendarList read-only, and Free/Busy.

## Calendar read / planning path

```text
user question / Calendar work area / selected scheduling mail
  -> load connected Calendar metadata
  -> list events and/or Google Free/Busy
  -> deterministic free-slot calculation (timezone/workday/duration/buffer)
  -> optional Calendar Concierge reasoning
  -> answer OR clarification OR typed proposal
```

Read-only questions do not create approvals. If required scheduling facts are missing, the Concierge is
instructed to return a clarification rather than inventing dates, locations, attendees, or commitments.

## Calendar mutation path

```text
owner scheduling request
  -> gateway-authoritative mailbox/calendar scope
  -> validate selected Calendar accessRole
  -> for update/delete: fetch current event + freeze ETag
  -> for create/update: deterministic conflict check
  -> enqueue separate Calendar approval
  -> human approve / reject
  -> atomic execution claim
  -> revalidate access role + conflict + ETag
  -> Google Calendar mutation
  -> complete/reconcile/fail explicitly
  -> audit event
```

Calendar never extends `MailActionType`. This prevents a mail-analysis result from becoming a direct
Calendar execution primitive.

### Create reliability

Each approved create receives a deterministic Google event ID derived from its Calendar approval ID and
a private `mailAgentApprovalId` marker. Before creation/retry, the executor checks that ID. If a previous
request succeeded but the response was lost, the existing matching event is reconciled instead of
creating a duplicate.

### Update/delete reliability

Update/delete proposals retain the source event ETag. Immediately before mutation, the executor fetches
the event again. A changed ETag prevents overwriting newer user/provider changes. If an update retry
finds the desired state already present, it reconciles success. If a delete retry finds the event already
missing, it reconciles success.

## Mail-to-Calendar bridge

Incoming mail is never allowed to cross the trust boundary on its own.

```text
synced local mail
  -> deterministic scheduling-intent detector
  -> UI hint only (zero side effects)
  -> owner chooses "Mit Kalender planen" or "Freie Zeiten antworten"
  -> source mail passed as explicitly UNTRUSTED context
```

For availability replies, Google Free/Busy is the authoritative schedule source. The LLM may only phrase
a short introductory sentence; the gateway inserts verified slot lines deterministically, stamps the
normal Agent-ID signature, and saves a mail draft. Sending that draft remains separately approval-gated.

## Credential vault

AES-256-GCM entries use fresh nonces and bind ciphertext to the vault reference as authenticated data.
The encrypted vault and master-key material are separate. OAuth tokens for Gmail and Calendar use the
same local vault abstraction; token values are never exposed by Calendar status endpoints.

## Local stores

- `mail.db` — normalized messages, drafts, mail approvals, processing state
- `calendar.db` — Calendar approvals and execution/recovery state only
- `conversations.db` — conversation state and sender-pattern intelligence
- `audit.jsonl` — append-only security/operation events
- `state.json` — non-secret configuration and capability metadata

Calendar approval audit data intentionally records IDs, action type, counts, and execution state rather
than event bodies, attendee lists, or OAuth credentials.

## Agent identity

During onboarding the gateway creates an Ed25519 keypair. The private key remains local; the registry
stores the public key, fingerprint, owner, and installation metadata. Outgoing agent-generated mail is
stamped/signed through the established mail draft path, including availability replies generated from
Calendar data.

## Provider architecture

Every LLM provider implements the same async interface:

- `health()`
- `list_models()`
- `complete(request)`

Calendar reasoning uses the same model routing layer as mail reasoning, but model output is still bound
to Calendar-specific typed schemas and separate gateway enforcement.
