from __future__ import annotations

from . import main as launcher

APP_VERSION = "0.17.0"
launcher.APP_VERSION = APP_VERSION

# Keep the established launcher lifecycle intact. Frozen builds must configure the current
# _MEIPASS/web environment before importing the additive 0.17 gateway layer.
_base_run = launcher._run


def _run_with_calendar_gateway(args):
    data_dir = (args.data_dir or launcher.user_data_dir()).resolve()
    launcher.configure_environment(data_dir)

    from mail_agent_gateway import main_v17 as _gateway_v17  # noqa: F401

    return _base_run(args)


def main() -> int:
    launcher._run = _run_with_calendar_gateway
    return launcher.main()
