# Product direction: Personal Operations Agent

## Product promise

MAIL-AGENT is becoming a local-first personal operations agent for normal users. It does not ask the
owner to manage another inbox. It continuously turns email and calendar state into four outcomes:

1. routine mail is handled within explicit owner rules;
2. replies and decisions are prepared before the owner sees them;
3. appointments, commitments and follow-ups are kept in sync;
4. one daily briefing shows only the work that still needs a human decision.

The short promise is: **MAIL-AGENT prepares the day and asks only when a real decision is needed.**

## Core product loop

```text
Observe mail and calendar
        -> understand requests, commitments and noise
        -> execute safe routine work within owner rules
        -> prepare replies, approvals and calendar actions
        -> brief the owner on the remaining decisions
        -> learn only from explicit owner feedback
```

This loop is the primary product. Inbox browsing, logs, rule editors and provider controls support it;
they are not the product's main navigation or value proposition.

## Jobs to be done

### Prepare replies and decisions

- recognize when the owner is expected to answer or decide;
- summarize the actual question and relevant thread context;
- prepare a reply in the owner's tone;
- show why the item needs attention;
- keep sending and forwarding behind the existing approval boundary.

### Organize appointments and commitments

- recognize concrete and ambiguous scheduling requests;
- check authoritative Calendar availability;
- create narrowly safe, conflict-free local events in Autonomous mode;
- keep rescheduling, cancellation, attendees and external notifications approval-gated;
- connect accepted appointments to the required confirmation reply.

### Remove low-value mail

- learn stable sender/category patterns only after sufficient evidence;
- archive or mark read only when an explicit automation allows it;
- retain Shadow mode, audit trails and undo for evaluation and recovery;
- never let a model redefine the safety policy from mail content.

### Produce a daily briefing

- combine mail attention, recovery states, approvals, ready drafts, follow-ups and today's agenda;
- rank by deterministic urgency instead of inbox arrival order;
- deduplicate the same work when it appears in mail and conversation state;
- provide a direct next action for every briefing item;
- degrade gracefully when Calendar is not connected or temporarily unavailable.

## Experience for normal users

Normal users should see three layers, in this order:

1. **Briefing** — what needs a decision now, what is prepared and what happens today;
2. **Work areas** — replies, follow-ups, approvals and Calendar when more detail is needed;
3. **Control center** — autonomy, rules, Shadow mode, security and diagnostics.

Technical language such as LLM routing, queues, traces, ETags and provider scopes belongs in the
control center and documentation. The primary UI should use outcome language: "Antwort vorbereitet",
"Termin eingetragen", "Wartet auf andere" and "Entscheidung nötig".

## Safety contract

The repositioning does not relax the existing trust boundaries:

- the model returns typed proposals and never receives direct mail or Calendar mutation tools;
- sending and forwarding remain human approval-gated;
- Calendar updates, deletes, attendees, notifications and conflicts remain approval-gated;
- only deterministic low-risk actions may be executed automatically;
- all autonomous actions remain locally auditable and recoverable where the provider supports it;
- incoming mail is always untrusted data, never policy or owner instruction.

## Delivery sequence

### 0.18 — Outcome-first briefing

- server-side `/v1/briefing` composition;
- deterministic ranking and deduplication;
- unified home screen for decisions, drafts, follow-ups and today's Calendar;
- direct routing from each briefing item to the relevant work area.

### 0.19 — Commitment ledger

- typed extraction of promises, requests, dates and deadlines;
- durable commitment state independent of inbox presence;
- owner confirmation for ambiguous obligations;
- completion, snooze and source-thread provenance.

### 0.20 — Outcome command

- replace the search-only command box with trusted owner instructions;
- support goals such as "prepare replies for everything urgent" or "find a time for this request";
- produce an execution plan before high-impact work;
- reuse the existing typed proposals, policies and approval queues.

### 0.21 — Autopilot receipts

- configurable low-risk automation bundles for normal users;
- concise "handled for you" receipts instead of technical journal noise;
- confidence and undo feedback that improve sender rules;
- measurable time saved and owner intervention rate.

### 1.0 — Consumer-ready release

- guided defaults rather than an expert configuration wall;
- clear recovery for expired provider connections;
- notification delivery for genuinely important decisions;
- signed installer/update pipeline and first-run health verification;
- accessibility, localization and end-to-end usability evaluation.

## Success measures

- owner decisions per 100 processed messages;
- percentage of reply-needed mail with a useful draft prepared;
- safe routine actions completed without intervention;
- false-positive attention and automation undo rates;
- commitments missed or detected too late;
- median time from sync to a decision-ready briefing item;
- weekly time saved, shown as an estimate with its calculation explained.

## Non-goals

- replacing the provider's full mail client;
- becoming a general-purpose shell or browser agent;
- hiding autonomous actions or making approval boundaries configurable by prompts;
- copying entire mailboxes into long-term model memory;
- adding integrations that do not improve the core operations loop.
