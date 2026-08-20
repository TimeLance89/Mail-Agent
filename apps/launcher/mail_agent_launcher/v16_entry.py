from __future__ import annotations

# Importing the 0.16 composition shim augments the existing gateway application in-place while
# preserving the established Policy/Identity/Executor/Queue composition from main.py.
from mail_agent_gateway import main_v16 as _gateway_v16  # noqa: F401

from . import main as launcher

APP_VERSION = "0.16.0"
launcher.APP_VERSION = APP_VERSION


def main() -> int:
    return launcher.main()
