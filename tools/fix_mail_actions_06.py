from pathlib import Path

path = Path("apps/gateway/mail_agent_gateway/mail_store.py")
text = path.read_text(encoding="utf-8")
old = '        success_status: str = "completed",\n'
new = '        success_status: str = "sent",\n'
if new not in text:
    if text.count(old) != 1:
        raise SystemExit("mail_store execution default marker missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
