from __future__ import annotations

import argparse
import logging
import os
import platform
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx
import uvicorn

APP_NAME = "MAIL-AGENT"
GATEWAY_PORT = 8765
REGISTRY_PORT = 8770


def user_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Mail-Agent"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Mail-Agent"
    root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "mail-agent"


def bundle_web_dir() -> Path | None:
    root = getattr(sys, "_MEIPASS", None)
    if not root:
        return None
    candidate = Path(root) / "mail_agent_web"
    return candidate if candidate.exists() else None


def configure_environment(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MAIL_AGENT_DATA_DIR", str(data_dir / "gateway"))
    os.environ.setdefault("MAIL_AGENT_REGISTRY_DB", str(data_dir / "registry" / "registry.db"))
    os.environ.setdefault("MAIL_AGENT_REGISTRY_URL", f"http://127.0.0.1:{REGISTRY_PORT}")
    os.environ.setdefault("MAIL_AGENT_GATEWAY_HOST", "127.0.0.1")
    os.environ.setdefault("MAIL_AGENT_GATEWAY_PORT", str(GATEWAY_PORT))
    web_dir = bundle_web_dir()
    if web_dir:
        os.environ.setdefault("MAIL_AGENT_WEB_DIR", str(web_dir))


def configure_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "mail-agent.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def run_server(app, port: int) -> None:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.run()


def wait_for_gateway(timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{GATEWAY_PORT}/health", timeout=0.8)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(prog="mail-agent")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()

    data_dir = (args.data_dir or user_data_dir()).resolve()
    configure_environment(data_dir)
    configure_logging(data_dir)

    # Imports happen after environment setup because both services resolve storage paths at import time.
    from mail_agent_registry.main import app as registry_app
    from mail_agent_gateway.main import app as gateway_app

    if port_is_open(GATEWAY_PORT):
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{GATEWAY_PORT}")
        return 0

    registry_thread = threading.Thread(
        target=run_server,
        args=(registry_app, REGISTRY_PORT),
        daemon=True,
        name="mail-agent-registry",
    )
    gateway_thread = threading.Thread(
        target=run_server,
        args=(gateway_app, GATEWAY_PORT),
        daemon=False,
        name="mail-agent-gateway",
    )
    registry_thread.start()
    time.sleep(0.2)
    gateway_thread.start()

    if wait_for_gateway() and not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{GATEWAY_PORT}")

    try:
        gateway_thread.join()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
