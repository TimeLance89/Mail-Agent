# Roadmap

The original foundation roadmap is complete and no longer describes the current product. MAIL-AGENT
already has Gmail, Microsoft Graph and IMAP/SMTP mail paths, durable drafts and approvals, owner
learning, conversation follow-ups, autonomous low-risk mail behavior, Google Calendar scheduling,
Shadow evaluation, a Windows installer and an update path.

The next roadmap is outcome-first:

## 0.18 — Daily operations briefing

- [x] deterministic briefing model for mail, approvals, drafts, follow-ups and Calendar;
- [x] `/v1/briefing` read-only aggregation endpoint;
- [x] start page centered on decisions and prepared work;
- [x] learning status and owner control visible in the briefing;
- [x] draft-correction learning disabled until explicit owner consent;
- [x] revocation deletes profile, signals and machine-learned correction memory;
- [x] safe onboarding restart preserving identity, connections and operational history;
- [ ] briefing completion actions without switching work areas;
- [ ] automation receipts: what was handled since the last briefing;
- [ ] benchmark briefing usefulness against real anonymized scenarios.

## 0.19 — Owner learning and progressive delegation

- [ ] unify profile, draft-correction and outcome learning in one control center;
- [ ] scoped consent by communication, priorities, contacts and workflows;
- [ ] evidence and benefit receipts for every confirmed preference;
- [ ] editable preference scopes and expiry/reconfirmation;
- [ ] per-domain delegation that never inherits from learning consent;
- [ ] measure avoided corrections without storing mail content.

## 0.20 — Commitments and deadlines

- [ ] typed commitment/deadline proposal schema;
- [ ] durable local commitment ledger with source provenance;
- [ ] ambiguity review and owner correction flow;
- [ ] completion, snooze and escalation states;
- [ ] Calendar/task linkage without weakening approval policy;
- [ ] missed-commitment and false-positive evaluations.

## 0.21 — Owner command surface

- [ ] trusted natural-language owner command endpoint;
- [ ] multi-item planning across mail and Calendar;
- [ ] preview of intended effects before sensitive actions;
- [ ] reuse existing typed mail/Calendar proposal executors;
- [ ] outcome history instead of raw command transcripts.

## 0.22 — Normal-user autopilot

- [ ] guided automation bundles and conservative defaults;
- [ ] plain-language autonomy setup;
- [ ] notification routing for decisions, failures and security items;
- [ ] time-saved and intervention-rate telemetry stored locally;
- [ ] reversible bulk cleanup with provider-aware safeguards.

## 1.0 — Consumer-ready release

- [ ] OS-native vault key wrapping (DPAPI/Keychain/Secret Service);
- [ ] signed releases and updater metadata;
- [ ] macOS and Linux packaging parity;
- [ ] recovery and device revocation flow;
- [ ] accessibility and localization review;
- [ ] end-to-end onboarding and recovery usability tests.

See [`PRODUCT_DIRECTION.md`](PRODUCT_DIRECTION.md) for the product promise, experience principles,
safety contract and success measures behind this roadmap.
