# Changelog

## 0.19.1 — 2026-08-25

### Fixed

- added `owner_instruction` support to the adaptive mail-agent adapter used by the production
  runtime;
- owner-directed work now bypasses deterministic and local-triage shortcuts so an explicit owner
  instruction cannot be ignored or replaced by routine classification;
- added a regression test covering the exact adaptive production path behind “An Agenten senden”.

## 0.19.0 — 2026-08-25

### Added

- visible “An Agenten senden” handoff directly below owner decisions in “Wartet auf dich”;
- trusted owner-directed analysis that keeps email content untrusted and all deterministic safety
  boundaries intact;
- automatic routing to the prepared draft or approval after the agent processes an instruction;
- explicit “Ohne Auftrag erledigen” path for decisions that need no further agent work.

### Safety

- owner instructions cannot override mailbox scope, recipient enforcement, Agent-ID signatures,
  action policy or approval requirements;
- sending and forwarding remain separately approval-gated;
- blocked instructions remain visible instead of being silently marked complete.

## 0.18.2 — 2026-08-25

### Fixed

- restored the `/v1/attention` endpoint by importing its execution-mode enum;
- added an end-to-end API regression test proving that a decision returned by the briefing can be
  loaded from “Wartet auf dich” without an HTTP 500 response.

## 0.18.1 — 2026-08-25

### Fixed

- briefing decisions now open the exact matching mail or approval instead of only switching views;
- stale briefing items completed or archived in the background refresh immediately and show a clear
  completion notice instead of an empty “Wartet auf dich” screen;
- owner reply work opens in the inbox rather than the unrelated “Wartet auf andere” queue;
- live dashboard refreshes now invalidate the briefing cache so completed work disappears promptly.

## 0.18.0 — 2026-08-24

### Added

- outcome-first daily briefing across attention, approvals, drafts, follow-ups and today's Calendar;
- visible owner-learning status and controls on the home screen;
- explicit owner learning contract and progressive trust roadmap;
- safe onboarding restart from Settings while preserving identity, connections and operational
  history;
- version-tag release publishing for Windows, Linux and macOS artifacts.

### Changed

- repositioned MAIL-AGENT as a personal operations agent for normal users;
- prioritized human decisions, prepared replies and commitments over inbox browsing;
- clarified learning and action authority as separate owner-controlled permissions.

### Privacy and safety

- draft corrections are not observed as learning signals until the owner opts in;
- every durable learned preference still requires explicit confirmation;
- revoking learning deletes the owner profile, correction signals and the dedicated machine-learned
  memory section;
- onboarding reset pauses the agent by removing the active behavior configuration before setup
  restarts;
- mail and Calendar mutation boundaries remain unchanged.
