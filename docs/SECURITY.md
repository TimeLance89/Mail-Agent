# Security model

## Non-negotiable rules

- Mailbox passwords, OAuth refresh tokens, and agent private keys must never be sent to the registry.
- Mailbox secrets must never be written to `state.json`, audit events, or the mail SQLite database.
- The model never receives raw credentials or access to the credential vault.
- The model never gets direct SMTP/IMAP or arbitrary shell execution.
- A model cannot approve its own proposed action.
- Sending, deletion, forwarding, and external-recipient changes are policy-controlled actions.
- High-impact actions remain approval-gated in v0.2.
- Every security-relevant decision produces an audit event.
- Work profiles default to stricter approval rules than private profiles.

## Credential vault

v0.2 encrypts mailbox secrets with AES-256-GCM. Each entry has an independent random nonce and uses
its vault reference as authenticated associated data, preventing ciphertext from being silently moved
between references. The master key is generated locally and stored separately with restrictive file
permissions where supported.

This protects against accidental disclosure of `state.json`, `mail.db`, backups containing only one
of those files, and casual inspection. It does **not** claim to protect against an attacker who has
full access to the local user account and both the vault and master-key files. OS-native key wrapping
is the planned hardening step.

## Mail synchronization

The background worker:

- selects IMAP folders read-only,
- uses stable UID cursors,
- fetches with `BODY.PEEK[]`,
- does not intentionally mutate read/unread state,
- ignores attachments in v0.2 parsing,
- persists transient sync failures without stopping the worker.

## Approval queue

Approval records are created by gateway code only after policy evaluation. They contain the frozen
proposal and policy decision at creation time. A record can transition from `pending` to exactly one
of `approved` or `rejected`; a second decision is rejected. The model-facing analysis path has no API
for deciding an approval.

Approval in v0.2 is a human decision record, **not yet automatic execution**. This separation is
intentional so the executor can later verify the stored proposal, mailbox scope, current policy, and
recipient before any high-impact side effect.

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
- contact address books unless a future feature has separate explicit consent

## Prompt injection

Email content is untrusted input. Instructions contained inside a message are data, not authority.
The agent prompt distinguishes system policy from mailbox content, and code-level policy checks
remain authoritative even if an LLM proposes an unsafe action.

## Autonomous mode

Autonomous mode does not mean unrestricted execution. High-impact actions can remain approval-only
or denied by policy regardless of the chosen autonomy level.
