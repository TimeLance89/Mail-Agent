from pathlib import Path


def replace_exact(path: str, old: str, new: str, *, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"Expected {expected} occurrence(s) of {old!r} in {path}, got {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "apps/gateway/mail_agent_gateway/main.py",
    'APP_VERSION = "0.6.0"',
    'APP_VERSION = "0.6.1"',
)
replace_exact(
    "apps/launcher/mail_agent_launcher/main.py",
    'APP_VERSION = "0.6.0"',
    'APP_VERSION = "0.6.1"',
)

web = Path("apps/web/app.js")
text = web.read_text(encoding="utf-8")
if "0.6.0" not in text:
    raise SystemExit("Expected 0.6.0 markers in apps/web/app.js")
web.write_text(text.replace("0.6.0", "0.6.1"), encoding="utf-8")
