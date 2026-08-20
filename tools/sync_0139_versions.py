from __future__ import annotations

import re
from pathlib import Path

VERSION = "0.13.9"
for relative in (
    "apps/gateway/mail_agent_gateway/main.py",
    "apps/launcher/mail_agent_launcher/main.py",
):
    path = Path(relative)
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
print(f"Synchronized runtime APP_VERSION to {VERSION}")
