from __future__ import annotations

import argparse
import ctypes
import logging
import os
import platform
import queue
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

APP_NAME = "MAIL-AGENT"
APP_VERSION = "0.2.4"
GATEWAY_PORT = 8765
REGISTRY_PORT = 8770
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"


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
    (data_dir / "gateway").mkdir(parents=True, exist_ok=True)
    (data_dir / "registry").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MAIL_AGENT_DATA_DIR", str(data_dir / "gateway"))
    os.environ.setdefault("MAIL_AGENT_REGISTRY_DB", str(data_dir / "registry" / "registry.db"))
    os.environ.setdefault("MAIL_AGENT_REGISTRY_URL", f"http://127.0.0.1:{REGISTRY_PORT}")
    os.environ.setdefault("MAIL_AGENT_GATEWAY_HOST", "127.0.0.1")
    os.environ.setdefault("MAIL_AGENT_GATEWAY_PORT", str(GATEWAY_PORT))
    web_dir = bundle_web_dir()
    if web_dir:
        os.environ.setdefault("MAIL_AGENT_WEB_DIR", str(web_dir))


def log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / "mail-agent.log"


def configure_logging(data_dir: Path) -> Path:
    path = log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(name)s %(message)s",
        force=True,
    )
    logging.info("Starting %s %s", APP_NAME, APP_VERSION)
    return path


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def gateway_health(timeout: float = 0.8) -> bool:
    try:
        import httpx

        response = httpx.get(f"{GATEWAY_URL}/health", timeout=timeout)
        payload = response.json() if response.status_code == 200 else {}
        return response.status_code == 200 and payload.get("service") == "mail-agent-gateway"
    except Exception:
        return False


def show_error_dialog(message: str, *, details: str | None = None) -> None:
    text = message
    if details:
        text = f"{message}\n\n{details}"
    if platform.system() == "Windows":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, "MAIL-AGENT – Startfehler", 0x10 | 0x0)
            return
        except Exception:
            pass
    logging.error("%s", text)


def show_info_dialog(message: str) -> None:
    if platform.system() == "Windows":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, "MAIL-AGENT", 0x40 | 0x0)
            return
        except Exception:
            pass
    logging.info("%s", message)


class StartupSplash:
    """Tiny native bootstrap window so a GUI launch never looks like a no-op."""

    def __init__(self) -> None:
        self.root: Any | None = None
        self.status: Any | None = None
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("MAIL-AGENT")
            root.geometry("460x190")
            root.resizable(False, False)
            root.configure(bg="#08111f")
            root.attributes("-topmost", True)
            root.protocol("WM_DELETE_WINDOW", lambda: None)
            frame = tk.Frame(root, bg="#08111f", padx=28, pady=24)
            frame.pack(fill="both", expand=True)
            tk.Label(
                frame,
                text="MAIL · AGENT",
                fg="#f4f7ff",
                bg="#08111f",
                font=("Segoe UI Semibold", 20),
            ).pack(anchor="w")
            tk.Label(
                frame,
                text="Dein lokaler Mail-Agent wird gestartet",
                fg="#8fa3c3",
                bg="#08111f",
                font=("Segoe UI", 10),
            ).pack(anchor="w", pady=(4, 22))
            self.status = tk.Label(
                frame,
                text="Initialisiere …",
                fg="#73a2ff",
                bg="#08111f",
                font=("Segoe UI", 10),
            )
            self.status.pack(anchor="w")
            self.root = root
            root.update_idletasks()
            root.update()
        except Exception:
            logging.exception("Could not create startup splash")
            self.root = None
            self.status = None

    def set_status(self, text: str) -> None:
        if self.root is None or self.status is None:
            return
        try:
            self.status.configure(text=text)
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            self.root = None
            self.status = None

    def close(self) -> None:
        if self.root is None:
            return
        try:
            self.root.destroy()
        except Exception:
            pass
        finally:
            self.root = None
            self.status = None


def run_server(app: Any, port: int, name: str, errors: queue.Queue[tuple[str, BaseException]]) -> None:
    try:
        import uvicorn

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            log_config=None,
        )
        server = uvicorn.Server(config)
        server.run()
    except BaseException as exc:
        logging.exception("%s server crashed", name)
        errors.put((name, exc))


def wait_for_gateway(
    errors: queue.Queue[tuple[str, BaseException]],
    *,
    timeout: float = 25.0,
    splash: StartupSplash | None = None,
) -> tuple[bool, str | None]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            name, exc = errors.get_nowait()
            return False, f"{name} konnte nicht gestartet werden: {exc}"
        except queue.Empty:
            pass
        if gateway_health():
            return True, None
        if splash is not None:
            remaining = max(0, int(deadline - time.monotonic()))
            splash.set_status(f"Lokales Gateway startet … ({remaining}s)")
        time.sleep(0.25)
    try:
        name, exc = errors.get_nowait()
        return False, f"{name} konnte nicht gestartet werden: {exc}"
    except queue.Empty:
        return False, "Das lokale Gateway hat nicht rechtzeitig geantwortet."


def open_app_browser() -> bool:
    try:
        return bool(webbrowser.open(GATEWAY_URL, new=1))
    except Exception:
        logging.exception("Could not open browser")
        return False


def _run(args: argparse.Namespace) -> int:
    data_dir = (args.data_dir or user_data_dir()).resolve()
    configure_environment(data_dir)
    path = configure_logging(data_dir)
    splash = None if args.no_browser else StartupSplash()

    try:
        if splash:
            splash.set_status("Komponenten werden geladen …")

        # Imports happen after environment setup because both services resolve storage paths at import time.
        from mail_agent_registry.main import app as registry_app
        from mail_agent_gateway.main import app as gateway_app

        if gateway_health():
            if splash:
                splash.close()
            if not args.no_browser and not open_app_browser():
                show_info_dialog(f"MAIL-AGENT läuft unter:\n\n{GATEWAY_URL}")
            return 0

        if port_is_open(GATEWAY_PORT):
            raise RuntimeError(
                f"Port {GATEWAY_PORT} wird bereits von einem anderen Programm verwendet."
            )

        errors: queue.Queue[tuple[str, BaseException]] = queue.Queue()
        if splash:
            splash.set_status("Registry wird gestartet …")

        registry_thread = threading.Thread(
            target=run_server,
            args=(registry_app, REGISTRY_PORT, "Registry", errors),
            daemon=True,
            name="mail-agent-registry",
        )
        gateway_thread = threading.Thread(
            target=run_server,
            args=(gateway_app, GATEWAY_PORT, "Gateway", errors),
            daemon=False,
            name="mail-agent-gateway",
        )
        registry_thread.start()
        time.sleep(0.15)
        gateway_thread.start()

        ready, reason = wait_for_gateway(errors, splash=splash)
        if not ready:
            raise RuntimeError(reason or "Unbekannter Startfehler")

        logging.info("Gateway ready at %s", GATEWAY_URL)
        if splash:
            splash.set_status("Bereit – Oberfläche wird geöffnet …")
            time.sleep(0.2)
            splash.close()

        if not args.no_browser and not open_app_browser():
            show_info_dialog(f"MAIL-AGENT läuft. Öffne im Browser:\n\n{GATEWAY_URL}")

        try:
            gateway_thread.join()
        except KeyboardInterrupt:
            return 0
        return 0
    except Exception as exc:
        logging.exception("MAIL-AGENT startup failed")
        if splash:
            splash.close()
        show_error_dialog(
            "MAIL-AGENT konnte nicht gestartet werden.",
            details=f"{exc}\n\nDiagnoseprotokoll:\n{path}",
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="mail-agent")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    try:
        return _run(args)
    except BaseException as exc:
        # Last-resort guard for windowed/frozen builds: never disappear silently.
        data_dir = (args.data_dir or user_data_dir()).resolve()
        try:
            configure_environment(data_dir)
            path = configure_logging(data_dir)
            logging.error("Fatal launcher error\n%s", traceback.format_exc())
            detail = f"{exc}\n\nDiagnoseprotokoll:\n{path}"
        except Exception:
            detail = str(exc)
        show_error_dialog("MAIL-AGENT ist unerwartet abgestürzt.", details=detail)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())