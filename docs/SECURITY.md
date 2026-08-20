# Security model

## Non-negotiable rules

- Mailbox passwords, OAuth refresh tokens, and agent private keys must never be sent to the registry.
- Mailbox/OAuth secrets must never be written to `state.json`, audit events, mail SQLite, Calendar SQLite, or agent memory.
- The model never receives raw credentials or direct access to the credential vault.
- The model never gets direct SMTP/IMAP, Google Calendar mutation, filesystem, or arbitrary shell execution.
- A model cannot approve its own proposed action.
- Mail sending/forwarding and Calendar create/update/delete/invite operations remain human approval-gated.
- Foreign email is untrusted input and cannot authorize a Calendar mutation, notification, attendee, conflict override, policy change, identity change, or approval bypass.
- Every security-relevant decision produces an audit event without storing credentials or full mail/calendar content.

## Credential vault

MAIL-AGENT encrypts mailbox and OAuth secrets with AES-256-GCM. Each entry has an independent random
nonce and uses its vault reference as authenticated associated data, preventing ciphertext from being
silently moved between references. The master key is generated locally and stored separately with
restrictive permissions or an OS-backed wrapper where supported.

This protects against accidental disclosure of `state.json`, `mail.db`, `calendar.db`, and casual
inspection. It does **not** claim to protect against an attacker who fully controls the local user
account and can access both encrypted vault and its unlocked master key.

## Mail synchronization

The IMAP worker uses read-only folder selection, stable UID cursors, and `BODY.PEEK[]` so ordinary
synchronization does not intentionally mutate read/unread state. Gmail and Microsoft connectors use
their provider APIs but persist the same normalized local message model. Credentials are resolved from
the vault only when a connector request is made.

## Mail approval boundary

Mail approval records are created by gateway code after deterministic policy evaluation. A model only
returns a typed proposal. Sending and forwarding cannot be converted into direct model tools. Approval
records freeze the proposal/policy state and have atomic decision/execution transitions; retry handling
prevents silent duplicate sends where delivery state is uncertain.

## Google Calendar capability boundary

Google Calendar is an optional capability on an already connected Google mailbox. Calendar OAuth uses
separate incremental consent for these scopes:

- `calendar.events`
- `calendar.calendarlist.readonly`
- `calendar.freebusy`

The access/refresh tokens use the same encrypted local OAuth vault as Gmail. Public status endpoints
expose capability/scopes but never the credential reference or token values.

Calendar has a **separate approval queue** from mail. The model-facing mail action schema is not widened
with Calendar execution tools. A Calendar Concierge can return one of three outcomes:

1. read-only answer,
2. clarification request,
3. typed Calendar mutation proposal.

Only the third can enter the Calendar approval queue, and it still cannot execute without an explicit
owner approval.

### Calendar write validation

Immediately before a proposal is queued, and again before an approved mutation executes, gateway code
checks the connected account, selected calendar, granted scopes, effective Google access role, event
identity, and conflicts.

Writable roles accepted from Google are `owner`, `writer`, and `writerWithoutPrivateAccess`. `reader`
and `freeBusyReader` remain non-writable.

For create/update operations, overlapping opaque events are treated as conflicts unless the owner
explicitly authorizes a conflict. A foreign email can never provide that authorization.

### Calendar retry and stale-data safety

- Creates use a deterministic Google event ID plus a private approval marker so a lost response or
  process restart can reconcile the same event instead of creating a duplicate.
- Updates freeze the source event ETag. If the event changed before execution, MAIL-AGENT refuses to
  overwrite it unless the remote result already matches the approved target state.
- Deletes also validate the ETag; an already-missing event is reconciled as already deleted.
- Calendar rows left in `executing` after a process interruption are recovered as explicit retryable
  failures rather than silently replayed in the background.

## Mail-to-Calendar prompt-injection boundary

Scheduling-related email detection is deterministic and side-effect free. Selecting a mail as Calendar
context does not grant authority to its sender. The Calendar prompt labels the mail body as untrusted
data, and gateway code overwrites mailbox/calendar/source IDs after model output.

When MAIL-AGENT prepares an availability reply, the LLM may phrase only a short introduction. Actual
free dates/times are computed from Google Free/Busy and inserted deterministically by the gateway. Lines
containing digits are removed from the model introduction as defense-in-depth against invented schedule
facts. The resulting email is stamped with the normal Agent-ID signature and still requires the normal
mail send approval.

## Agent registration data

Allowed remote fields:

- owner ID
- agent ID
- installation ID
- agent name
- usage type
- public key
- public-key fingerprint
- app version
- creation / last-seen timestamps

Explicitly forbidden remote fields:

- private keys
- mailbox credentials
- OAuth refresh/access tokens
- email bodies or attachments
- Calendar event bodies/titles/attendees
- contact address books unless a future feature has separate explicit consent

## Autonomous mode

Autonomous mode does not mean unrestricted execution. Mail high-impact actions and **all Calendar
mutations** remain approval-gated or can be denied regardless of the selected autonomy level. Calendar
read operations and deterministic availability computation may run without a write approval because
they have no Calendar side effect.
