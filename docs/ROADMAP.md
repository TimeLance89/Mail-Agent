# Roadmap

## v0.1 — Trusted foundation

- [x] Gateway API
- [x] Registry API
- [x] Mandatory Ed25519 agent identity
- [x] Ollama provider adapter
- [x] Codex CLI adapter skeleton
- [x] Policy engine and autonomy modes
- [x] IMAP/SMTP connector primitives
- [x] Onboarding UI
- [x] Core tests

## v0.2 — Mailbox sync

- [ ] Background IMAP sync worker
- [ ] Thread normalization and local message index
- [ ] Gmail OAuth connector
- [ ] Microsoft Graph / Outlook OAuth connector
- [ ] Credential vault abstraction
- [ ] Draft generation pipeline
- [ ] Approval queue UI

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
- [ ] Rollback-safe mailbox operations where supported

## v1.0 — Distribution

- [ ] Windows installer/service
- [ ] macOS launch agent/package
- [ ] Linux systemd/package
- [ ] Production registry on PostgreSQL
- [ ] Signed releases and updater
- [ ] Recovery / device revocation flow
