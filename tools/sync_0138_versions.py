from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.13.8"

for relative in (
    "apps/gateway/mail_agent_gateway/main.py",
    "apps/launcher/mail_agent_launcher/main.py",
):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^APP_VERSION = "[^"]+"$',
        f'APP_VERSION = "{VERSION}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit(f"Could not synchronize APP_VERSION in {relative}")
    path.write_text(updated, encoding="utf-8")

print(f"Synchronized source APP_VERSION to {VERSION}")
