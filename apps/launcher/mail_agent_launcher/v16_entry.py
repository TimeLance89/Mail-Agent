from __future__ import annotations

from . import main as launcher

APP_VERSION = "0.16.1"
launcher.APP_VERSION = APP_VERSION

# Keep the established launcher lifecycle intact. The adaptive gateway must not be imported at
# module import time: frozen builds first need configure_environment() to replace any stale
# MAIL_AGENT_WEB_DIR with the current _MEIPASS bundle path.
_base_run = launcher._run


def _run_with_adaptive_gateway(args):
    data_dir = (args.data_dir or launcher.user_data_dir()).resolve()
    launcher.configure_environment(data_dir)

    # Import only after the environment is authoritative. main_v16 augments the same base FastAPI
    # application that launcher._run imports a moment later, without changing Policy/Executor/Queue.
    from mail_agent_gateway import main_v16 as _gateway_v16  # noqa: F401

    return _base_run(args)


def main() -> int:
    launcher._run = _run_with_adaptive_gateway
    return launcher.main()
