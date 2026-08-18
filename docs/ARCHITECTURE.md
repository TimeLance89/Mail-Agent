# Architecture

## Trust boundaries

MAIL-AGENT has four primary boundaries:

1. **Mailbox boundary** — IMAP/SMTP or provider OAuth credentials stay in the local gateway.
2. **Model boundary** — the gateway decides what message context is sent to the selected model.
3. **Action boundary** — models only return structured proposals; they never execute mail actions.
4. **Identity boundary** — the remote registry receives only public installation identity metadata.

## Runtime topology

```text
Browser UI (localhost:8765)
          |
          v
Gateway (localhost:8765)
  |       |        |
  |       |        +--> LLM provider (Ollama / Codex CLI)
  |       +-----------> Mail connector (IMAP/SMTP; OAuth providers later)
  +-------------------> Registry (public identity metadata only)
```

## Core processing path

```text
incoming mail
  -> normalize
  -> security/classification
  -> context builder
  -> LLM
  -> MailActionProposal
  -> PolicyEngine
  -> allow / require approval / deny
  -> executor
  -> audit event
```

## Why the model cannot execute tools directly

Email is a high-impact domain: a wrong recipient, deletion, or automatic reply can have real
consequences. Restricting the model to a closed action schema makes the gateway the enforcement
point. Prompt injection can influence a proposal, but cannot bypass code-level policy checks.

## Agent identity

During onboarding the gateway creates an Ed25519 keypair. The private key is stored only in the
local data directory with restrictive permissions. The registry stores the public key and a SHA-256
fingerprint plus owner and installation metadata. Requests can later be signed by the gateway and
verified by the registry.

## Provider architecture

Every LLM provider implements the same async interface:

- `health()`
- `list_models()`
- `complete(request)`

The agent core therefore has no provider-specific dependency. Ollama communicates over local HTTP.
The Codex adapter uses the locally installed Codex client and its own authentication state.
