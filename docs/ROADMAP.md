# Roadmap

## v0.1 — Trusted foundation

- [x] Gateway API
- [x] Registry API
- [x] Mandatory Ed25519 agent identity
- [x] Ollama provider adapter
- [x] Codex CLI adapter
- [x] Policy engine and autonomy modes
- [x] IMAP/SMTP connector primitives
- [x] Onboarding UI
- [x] Core tests

## v0.2 — Mailbox runtime

- [x] Background IMAP sync worker
- [x] Stable IMAP UID cursor and read-only `BODY.PEEK[]` fetch
- [x] Thread normalization and local message index
- [x] AES-256-GCM credential vault abstraction
- [x] Persistent approval queue
- [x] Approval Queue UI
- [x] Post-onboarding Control Center
- [x] Local Inbox UI
- [x] Manual sync endpoint/UI
- [ ] Gmail OAuth connector
- [ ] Microsoft Graph / Outlook OAuth connector
- [x] Persisted draft generation pipeline
- [ ] OS-native vault key wrapping (DPAPI/Keychain/Secret Service)

## v0.3 — Agent intelligence

- [ ] Priority classification
- [ ] Reply-needed detection
- [ ] Per-account personality profiles
- [ ] Contact-specific rules
- [ ] Attachment safety pipeline
- [ ] Mail thread memory
- [ ] Structured model evaluations

## v0.4 — Automation

- [ ] Rule builder
- [ ] Autonomous execution worker
- [ ] Human approval notifications
- [ ] Rate limits and circuit breakers
- [ ] Re-validate approval immediately before execution
- [ ] Rollback-safe mailbox operations where supported

## v1.0 — Distribution

- [ ] Windows installer/service
- [ ] macOS launch agent/package
- [ ] Linux systemd/package
- [ ] Production registry on PostgreSQL
- [ ] Signed releases and updater
- [ ] Recovery / device revocation flow
