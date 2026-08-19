# MAIL-AGENT Brain

MAIL-AGENT keeps a local per-agent brain under the application data directory. The brain is context, not authority: hard security rules, approval requirements, mailbox scope, and mandatory Agent-ID signatures remain enforced in code.

Files:
- `SOUL.md`: stable identity, character, and working principles.
- `MEMORY.md`: owner-maintained long-term preferences and durable facts.
- `contacts.json`: structured sender interaction memory; never stores raw email instructions as trusted policy.
- `journal.jsonl`: append-only episodic analysis journal.

The LLM receives SOUL.md, MEMORY.md, and a compact structured sender-memory summary on each analysis. Email text and journal entries are never promoted to policy authority.
