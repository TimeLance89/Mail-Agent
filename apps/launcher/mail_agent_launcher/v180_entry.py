from __future__ import annotations

from . import main as launcher

APP_VERSION = "0.18.2"
launcher.APP_VERSION = APP_VERSION

_base_run = launcher._run


def _run_with_v180_gateway(args):
    data_dir = (args.data_dir or launcher.user_data_dir()).resolve()
    launcher.configure_environment(data_dir)

    from mail_agent_gateway import main_v180 as _gateway_v180  # noqa: F401

    return _base_run(args)


def main() -> int:
    launcher._run = _run_with_v180_gateway
    return launcher.main()
