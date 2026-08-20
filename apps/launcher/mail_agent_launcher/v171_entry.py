from __future__ import annotations

from . import main as launcher

APP_VERSION = "0.17.1"
launcher.APP_VERSION = APP_VERSION

_base_run = launcher._run


def _run_with_v171_gateway(args):
    data_dir = (args.data_dir or launcher.user_data_dir()).resolve()
    launcher.configure_environment(data_dir)

    from mail_agent_gateway import main_v171 as _gateway_v171  # noqa: F401

    return _base_run(args)


def main() -> int:
    launcher._run = _run_with_v171_gateway
    return launcher.main()
