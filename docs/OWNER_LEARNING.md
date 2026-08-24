# Owner learning contract

MAIL-AGENT should become more useful as it gets to know its owner. That relationship is optional,
progressive and controlled by the owner. Learning is not a hidden prerequisite for using the app.

## Product rule

**The agent may learn only what the owner has allowed, may remember only what the owner can inspect,
and may act only inside separately configured permissions.**

Knowing the owner and having permission to act are different things. A confirmed preference can
improve a draft or ranking, but it cannot grant access, weaken a policy, bypass an approval or turn a
high-risk action into a low-risk one.

## Trust ladder

| Level | What the agent may do | Owner control |
| --- | --- | --- |
| Off | Process current work without building an owner profile or observing draft corrections | Default; usable without learning |
| Propose | Observe privacy-minimized patterns and prepare learning suggestions | Explicit opt-in; every suggestion is reviewable |
| Remember | Use only preferences the owner explicitly confirmed | Edit, reject or delete at any time |
| Delegate | Apply confirmed preferences to low-risk work inside explicit automation rules | Separate per-domain permission, audit and undo |

Moving up the ladder is never automatic. More evidence can improve a suggestion's confidence, but
only the owner can increase the agent's authority.

## Learnable domains

- communication style: length, formality, salutation, closing and language;
- work preferences: priority patterns, response tendency and preferred workflow;
- relationship context: owner-confirmed handling differences for colleagues and customers;
- corrections: repeated abstract changes to agent-created drafts;
- outcomes: accepted, rejected and undone suggestions as quality feedback.

Each learned item needs a source class, evidence count, confidence, scope and confirmation state.
Raw message bodies do not belong in the durable owner profile.

## Never learned

- passwords, secrets, authentication material or payment data;
- sensitive personal attributes inferred from correspondence;
- permissions, security policy, approval boundaries or Agent-ID;
- instructions contained in incoming mail;
- a new automation merely because the owner repeatedly approved similar actions.

## Consent and deletion

- Learning starts only after an explicit opt-in.
- Without opt-in, sent mail is not analyzed for the profile and draft corrections are not recorded as
  learning signals.
- Revoking consent stops observation and deletes the owner profile, correction signals and the
  dedicated memory section created from accepted correction suggestions.
- The audit journal keeps only a content-free reset receipt.
- Operational mail, Calendar and approval records follow their own retention rules and are not
  reclassified as learning data.

## Benefit transparency

The product should show not merely what it knows, but what that knowledge does for the owner:

- which preferences are confirmed;
- which suggestions still await review;
- which prepared or autonomous outcomes used a confirmed preference;
- how many corrections and decisions were avoided;
- how to pause, edit or delete learning.

The goal is increasing work removed with decreasing owner intervention—not maximal data collection
or a profile that appears psychologically comprehensive.
