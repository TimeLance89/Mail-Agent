from __future__ import annotations

import argparse
import ctypes
import logging
import os
import platform
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

from mail_agent_core.update import UpdateClient

from .desktop_runtime import (
    DesktopGatewayClient,
    DesktopNotification,
    DesktopStatus,
    NotificationTracker,
    desktop_view_url,
)

APP_NAME = "MAIL-AGENT"
APP_VERSION = "0.16.1"
GATEWAY_PORT = 8765
REGISTRY_PORT = 8770
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"
UPDATE_FEED_URL = os.getenv(
    "MAIL_AGENT_UPDATE_FEED_URL",
    "https://api.github.com/repos/TimeLance89/Mail-Agent/releases/tags/preview-latest",
)
UPDATE_RELEASE_PAGE = os.getenv(
    "MAIL_AGENT_UPDATE_RELEASE_PAGE",
    "https://github.com/TimeLance89/Mail-Agent/releases/tag/preview-latest",
)
UPDATE_TOKEN = os.getenv("MAIL_AGENT_UPDATE_TOKEN", "").strip() or None
AUTO_UPDATE_CHECK_SECONDS = max(
    3600, int(os.getenv("MAIL_AGENT_AUTO_UPDATE_CHECK_SECONDS", "21600"))
)
DESKTOP_STATUS_POLL_SECONDS = max(
    15, int(os.getenv("MAIL_AGENT_DESKTOP_STATUS_POLL_SECONDS", "30"))
)


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
        # `_MEIPASS` changes on every one-file PyInstaller start. An updater child process can
        # inherit MAIL_AGENT_WEB_DIR from the previous bundle, which points at an already removed
        # temporary directory. The current frozen bundle is authoritative and must replace it.
        os.environ["MAIL_AGENT_WEB_DIR"] = str(web_dir)


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


def show_confirm_dialog(message: str, *, title: str = "MAIL-AGENT") -> bool:
    if platform.system() == "Windows":
        try:
            # MB_YESNO | MB_ICONINFORMATION, IDYES == 6
            return ctypes.windll.user32.MessageBoxW(None, message, title, 0x04 | 0x40) == 6
        except Exception:
            pass
    return False


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


def run_server(
    app: Any,
    port: int,
    name: str,
    errors: queue.Queue[tuple[str, BaseException]],
    servers: dict[str, Any] | None = None,
) -> None:
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
        if servers is not None:
            servers[name] = server
        server.run()
    except BaseException as exc:
        logging.exception("%s server crashed", name)
        errors.put((name, exc))


def stop_servers(servers: dict[str, Any]) -> None:
    for server in list(servers.values()):
        try:
            server.should_exit = True
        except Exception:
            logging.exception("Could not stop server")


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


def open_app_view(view: str = "overview") -> bool:
    try:
        return bool(webbrowser.open(desktop_view_url(GATEWAY_URL, view), new=1))
    except Exception:
        logging.exception("Could not open browser")
        return False


def open_app_browser() -> bool:
    return open_app_view("overview")


class DesktopTray:
    def __init__(self, *, servers: dict[str, Any], data_dir: Path) -> None:
        self.servers = servers
        self.data_dir = data_dir
        self.icon: Any | None = None
        self._pystray: Any | None = None
        self.update_client = UpdateClient(
            feed_url=UPDATE_FEED_URL,
            release_page=UPDATE_RELEASE_PAGE,
            token=UPDATE_TOKEN,
        )
        self.gateway = DesktopGatewayClient(GATEWAY_URL)
        self.notifications = NotificationTracker()
        self.status = DesktopStatus(
            key="active",
            label="Aktiv",
            paused=False,
            execution_mode="live",
            approval_count=0,
            draft_count=0,
            pending_count=0,
            health_overall="unknown",
        )
        self._update_lock = threading.Lock()
        self._desktop_lock = threading.Lock()
        self._quit_event = threading.Event()
        self._last_prompted_version: str | None = None

    @staticmethod
    def _image() -> Any:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (10, 15, 27, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill=(112, 126, 255, 255))
        draw.rectangle((16, 20, 48, 44), outline=(255, 255, 255, 255), width=3)
        draw.line((16, 21, 32, 34, 48, 21), fill=(255, 255, 255, 255), width=3)
        return image

    def open_ui(self, *_: Any) -> None:
        open_app_view("overview")

    def open_activity(self, *_: Any) -> None:
        open_app_view("activity")

    def open_approvals(self, *_: Any) -> None:
        open_app_view("approvals")

    def open_health(self, *_: Any) -> None:
        open_app_view("system")

    def _menu(self) -> Any:
        pystray = self._pystray
        if pystray is None:
            return None
        work = (
            f"{self.status.approval_count} Freigaben · "
            f"{self.status.draft_count} Entwürfe · {self.status.pending_count} warten"
        )
        pause_label = "Agent fortsetzen" if self.status.paused else "Agent pausieren"
        return pystray.Menu(
            pystray.MenuItem("MAIL-AGENT öffnen", self.open_ui, default=True),
            pystray.MenuItem(f"Status: {self.status.label}", None, enabled=False),
            pystray.MenuItem(work, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_label, self.toggle_agent),
            pystray.MenuItem("Aktivität öffnen", self.open_activity),
            pystray.MenuItem("Freigaben öffnen", self.open_approvals),
            pystray.MenuItem("Systemzustand öffnen", self.open_health),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Nach Updates suchen", self.check_updates),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", self.quit),
        )

    def _refresh_menu(self) -> None:
        if self.icon is None or self._pystray is None:
            return
        try:
            self.icon.menu = self._menu()
            self.icon.title = f"MAIL-AGENT · {self.status.label}"
            self.icon.update_menu()
        except Exception:
            logging.exception("Could not refresh tray menu")

    def _notify(self, notification: DesktopNotification) -> None:
        if self.icon is None:
            return
        try:
            self.icon.notify(notification.message, notification.title)
        except Exception:
            logging.exception("Desktop notification failed")

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        status = snapshot.get("status")
        if isinstance(status, DesktopStatus):
            self.status = status
        events = self.notifications.observe(
            approvals=list(snapshot.get("approvals") or []),
            drafts=list(snapshot.get("drafts") or []),
            health=dict(snapshot.get("health") or {}),
        )
        self._refresh_menu()
        for event in events:
            self._notify(event)

    def _refresh_desktop_state(self) -> None:
        if not self._desktop_lock.acquire(blocking=False):
            return
        try:
            self._apply_snapshot(self.gateway.snapshot())
        except Exception:
            logging.exception("Desktop status refresh failed")
        finally:
            self._desktop_lock.release()

    def _desktop_monitor_loop(self) -> None:
        if self._quit_event.wait(2):
            return
        while not self._quit_event.is_set():
            self._refresh_desktop_state()
            if self._quit_event.wait(DESKTOP_STATUS_POLL_SECONDS):
                return

    def toggle_agent(self, *_: Any) -> None:
        threading.Thread(
            target=self._toggle_agent_worker,
            daemon=True,
            name="mail-agent-pause-toggle",
        ).start()

    def _toggle_agent_worker(self) -> None:
        target_enabled = self.status.paused
        if not self._desktop_lock.acquire(blocking=False):
            return
        try:
            self.gateway.set_enabled(target_enabled)
            self._apply_snapshot(self.gateway.snapshot())
            message = "Agent arbeitet wieder." if target_enabled else "Agent wurde pausiert."
            self._notify(
                DesktopNotification(
                    title="MAIL-AGENT",
                    message=message,
                    view="overview",
                )
            )
        except Exception:
            logging.exception("Could not change agent state from tray")
            self._notify(
                DesktopNotification(
                    title="MAIL-AGENT",
                    message="Der Agentenstatus konnte nicht geändert werden.",
                    view="system",
                )
            )
        finally:
            self._desktop_lock.release()

    def check_updates(self, *_: Any) -> None:
        threading.Thread(
            target=self._check_updates_worker,
            kwargs={"interactive": True},
            daemon=True,
            name="mail-agent-update-check",
        ).start()

    def _auto_update_loop(self) -> None:
        # Give the local services a moment to settle before doing network I/O.
        if self._quit_event.wait(12):
            return
        while not self._quit_event.is_set():
            self._check_updates_worker(interactive=False)
            if self._quit_event.wait(AUTO_UPDATE_CHECK_SECONDS):
                return

    def _stage_update_installer(self, info: Any) -> Path:
        updates_dir = self.data_dir / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        destination = updates_dir / f"Mail-Agent-Setup-{info.latest_version}.exe"
        return self.update_client.download(info, destination)

    def _launch_installer_after_exit(self, installer: Path) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("Automatische In-Place-Updates werden derzeit nur unter Windows unterstützt")
        helper = installer.with_name("apply-mail-agent-update.cmd")
        helper.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'"{installer}" /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS\r\n'
            'del "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(helper)],
            close_fds=True,
            creationflags=creationflags,
        )

    def _check_updates_worker(self, *, interactive: bool) -> None:
        if not self._update_lock.acquire(blocking=False):
            return
        try:
            info = self.update_client.check(APP_VERSION)
            if info.error:
                logging.warning("Update feed unavailable: %s", info.error)
                if interactive and show_confirm_dialog(
                    "Der automatische Update-Kanal ist momentan nicht erreichbar.\n\n"
                    "Soll die MAIL-AGENT Download-Seite im Browser geöffnet werden?",
                    title="MAIL-AGENT – Update",
                ):
                    webbrowser.open(info.release_page)
                return
            if not info.available:
                if interactive:
                    show_info_dialog(f"MAIL-AGENT {APP_VERSION} ist aktuell.")
                return
            if not interactive and self._last_prompted_version == info.latest_version:
                return
            self._last_prompted_version = info.latest_version
            if not show_confirm_dialog(
                f"MAIL-AGENT {info.latest_version} ist verfügbar.\n\n"
                "Das Update wird geprüft, installiert und MAIL-AGENT danach automatisch neu gestartet.\n\n"
                "Jetzt aktualisieren?",
                title="MAIL-AGENT – Update verfügbar",
            ):
                return
            installer = self._stage_update_installer(info)
            logging.info("Verified update staged at %s", installer)
            self._launch_installer_after_exit(installer)
            self.quit()
        except Exception as exc:
            logging.exception("Update installation failed")
            show_error_dialog("Update konnte nicht installiert werden.", details=str(exc))
        finally:
            self._update_lock.release()

    def quit(self, *_: Any) -> None:
        self._quit_event.set()
        stop_servers(self.servers)
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                logging.exception("Could not stop tray icon")

    def run(self) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            import pystray

            self._pystray = pystray
            self.icon = pystray.Icon(
                "MAIL-AGENT",
                self._image(),
                f"MAIL-AGENT · {self.status.label}",
                self._menu(),
            )
            threading.Thread(
                target=self._desktop_monitor_loop,
                daemon=True,
                name="mail-agent-desktop-status",
            ).start()
            threading.Thread(
                target=self._auto_update_loop,
                daemon=True,
                name="mail-agent-auto-update",
            ).start()
            self.icon.run()
            return True
        except Exception:
            logging.exception("Tray could not be started")
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
        servers: dict[str, Any] = {}
        if splash:
            splash.set_status("Registry wird gestartet …")

        registry_thread = threading.Thread(
            target=run_server,
            args=(registry_app, REGISTRY_PORT, "Registry", errors, servers),
            daemon=True,
            name="mail-agent-registry",
        )
        gateway_thread = threading.Thread(
            target=run_server,
            args=(gateway_app, GATEWAY_PORT, "Gateway", errors, servers),
            daemon=True,
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

        tray = DesktopTray(servers=servers, data_dir=data_dir)
        if tray.run():
            return 0

        # Fallback for platforms without a tray backend.
        try:
            while gateway_thread.is_alive():
                gateway_thread.join(timeout=0.5)
        except KeyboardInterrupt:
            stop_servers(servers)
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
