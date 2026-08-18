# Security model

## Non-negotiable rules

- Mailbox passwords, OAuth refresh tokens, and agent private keys must never be sent to the registry.
- The model never receives raw credentials.
- The model never gets direct access to SMTP/IMAP or arbitrary shell execution.
- Sending, deletion, forwarding, and external-recipient changes are policy-controlled actions.
- Every executed or rejected action produces an audit event.
- Work profiles default to stricter approval rules than private profiles.

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
The agent prompt must distinguish system policy from mailbox content, and code-level policy checks
remain authoritative even if an LLM proposes an unsafe action.

## Autonomous mode

Autonomous mode does not mean unrestricted execution. High-impact actions can remain approval-only
or denied by policy regardless of the chosen autonomy level.
