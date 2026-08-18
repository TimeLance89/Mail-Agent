# Architecture

## Trust boundaries

MAIL-AGENT has five primary boundaries:

1. **Mailbox boundary** — IMAP/SMTP credentials stay in the local encrypted vault.
2. **Local storage boundary** — mail content and approval state stay in the local SQLite database.
3. **Model boundary** — the gateway decides what message context is sent to the selected model.
4. **Action boundary** — models only return structured proposals; they never approve or execute mail actions.
5. **Identity boundary** — the remote registry receives only public installation identity metadata.

## Runtime topology

```text
Browser UI (localhost:8765)
          |
          v
Gateway (localhost:8765)
  |       |          |             |
  |       |          |             +--> LLM provider (Ollama / Codex CLI)
  |       |          +----------------> encrypted credential vault
  |       +---------------------------> SQLite mail + approval store
  +-----------------------------------> Registry (public identity metadata only)
          |
          +--> IMAP/SMTP mailbox
```

## Mail synchronization path

```text
sync scheduler / manual sync
  -> load non-secret mailbox metadata
  -> decrypt credential from vault
  -> IMAP readonly select
  -> search stable UIDs after stored cursor
  -> fetch via BODY.PEEK[] + FLAGS
  -> parse headers/body (attachments ignored in v0.2)
  -> derive thread key
  -> SQLite upsert
  -> advance sync cursor
  -> audit event
```

The cursor uses IMAP UIDs rather than sequence numbers because sequence numbers can change when a
mailbox changes. `BODY.PEEK[]` prevents synchronization from marking messages as read.

## Agent processing path

```text
local/incoming mail
  -> normalized MailMessageContext
  -> LLM
  -> MailActionProposal
  -> PolicyEngine
  -> allow / require approval / deny
  -> if approval required: persistent Approval Queue
  -> human approve / reject
  -> executor (future automation layer)
  -> audit event
```

## Why the model cannot execute tools directly

Email is a high-impact domain: wrong recipients, deletion, forwarding, or automatic replies can have
real consequences. Restricting the model to a closed action schema makes the gateway the enforcement
point. Prompt injection can influence a proposal but cannot approve it, retrieve credentials, or
bypass code-level policy checks.

## Credential vault

v0.2 uses AES-256-GCM with a fresh nonce per secret and binds ciphertext to its vault reference as
additional authenticated data. The encrypted vault file and the master key are separate files; both
receive restrictive permissions where supported. The master key is intentionally abstracted behind
`CredentialVault` so a later Windows DPAPI/macOS Keychain/Linux Secret Service wrapper can replace
file-backed key storage without changing mailbox connectors.

## Local mail store

SQLite stores normalized messages, stable sync state, and approval records. WAL mode is enabled to
allow the background sync and UI reads to coexist. Mailbox credentials are explicitly excluded from
the database.

## Agent identity

During onboarding the gateway creates an Ed25519 keypair. The private key is stored only in the local
data directory with restrictive permissions. The registry stores the public key and a SHA-256
fingerprint plus owner and installation metadata. Registration requests are signed locally.

## Provider architecture

Every LLM provider implements the same async interface:

- `health()`
- `list_models()`
- `complete(request)`

The agent core therefore has no provider-specific dependency. Ollama communicates over local HTTP.
The Codex adapter uses the locally installed Codex client and its own authentication state.
