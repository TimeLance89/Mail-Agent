from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep backlog semantics: running claims are still unfinished work, but cannot be claimed again.
path = ROOT / "apps/gateway/mail_agent_gateway/agent_queue.py"
text = path.read_text(encoding="utf-8")
marker = "    def pending_count(self, mailbox_id: str) -> int:\n"
head, tail = text.split(marker, 1)
tail = tail.replace("AND (p.status IS NULL OR p.status='error')", "AND (p.status IS NULL OR p.status IN ('error', 'running'))", 1)
path.write_text(head + marker + tail, encoding="utf-8")

# Important-mail desktop destinations must accept the new attention route.
path = ROOT / "apps/launcher/mail_agent_launcher/desktop_runtime.py"
text = path.read_text(encoding="utf-8")
text = text.replace('    "inbox",\n    "approvals",', '    "inbox",\n    "attention",\n    "approvals",', 1)
path.write_text(text, encoding="utf-8")

# Update the established desktop contracts for the intentionally changed destination.
path = ROOT / "tests/test_desktop_runtime.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '    assert desktop_view_url("http://127.0.0.1:8765", "approvals").endswith("/?view=approvals")\n',
    '    assert desktop_view_url("http://127.0.0.1:8765", "approvals").endswith("/?view=approvals")\n'
    '    assert desktop_view_url("http://127.0.0.1:8765", "attention").endswith("/?view=attention")\n',
    1,
)
text = text.replace('("Dringende E-Mail erkannt", "inbox")', '("Dringende E-Mail erkannt", "attention")', 1)
text = text.replace('("Sicherheitsrelevante E-Mail erkannt", "inbox")', '("Sicherheitsrelevante E-Mail erkannt", "attention")', 1)
path.write_text(text, encoding="utf-8")

# Self-clean staging infrastructure.
(ROOT / ".github/workflows/fix-0138-ci.yml").unlink(missing_ok=True)
Path(__file__).unlink(missing_ok=True)
