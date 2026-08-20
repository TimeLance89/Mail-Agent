from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESTART_HELPER = ROOT / "packaging/windows/restart-mail-agent.cmd"
INSTALLER = ROOT / "packaging/windows/MailAgent.iss"


def test_restart_helper_requires_the_new_gateway_to_be_healthy():
    source = RESTART_HELPER.read_text(encoding="utf-8")

    # Keep the critical PyInstaller child-process reset. Without it a freshly installed frozen
    # executable can inherit the old bundle environment and fail immediately after an update.
    assert 'set "PYINSTALLER_RESET_ENVIRONMENT=1"' in source

    # The old one-file bundle path is temporary and must never reach the newly installed process.
    assert 'set "MAIL_AGENT_WEB_DIR="' in source

    # A stale pre-update process must never be accepted as a successful restart.
    assert 'taskkill /F /T /IM "Mail-Agent.exe"' in source
    assert "Invoke-RestMethod" in source
    assert "MAIL_AGENT_HEALTH_URL" in source
    assert "MAIL_AGENT_EXPECTED_VERSION" in source
    assert "$r.service -eq 'mail-agent-gateway'" in source
    assert "$r.version -eq $env:MAIL_AGENT_EXPECTED_VERSION" in source

    # Restart is verified, retried once, and leaves a user-visible diagnostic on final failure.
    assert "First restart did not expose the expected gateway. Retrying once." in source
    assert "update-restart.log" in source
    assert "MessageBox" in source
    assert "--no-browser" in source

    # `timeout.exe` can fail in hidden/non-interactive installer contexts. Waiting must stay
    # console-independent.
    assert "timeout /t" not in source.lower()
    assert "Start-Sleep" in source


def test_inno_installer_passes_version_and_restart_mode_to_verifier():
    source = INSTALLER.read_text(encoding="utf-8")

    assert '#define MyAppVersion "0.13.8"' in source
    assert '""{#MyAppVersion}"" ""open-browser"""' in source
    assert '""{#MyAppVersion}"" ""no-browser"""' in source
    assert "postinstall skipifsilent" in source
    assert "skipifnotsilent" in source


class _HealthHandler(BaseHTTPRequestHandler):
    version = "0.13.8"

    def do_GET(self):  # noqa: N802 - stdlib callback name
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(
            {"status": "ok", "service": "mail-agent-gateway", "version": self.version}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows restart helper integration")
def test_restart_helper_accepts_only_expected_healthy_version(tmp_path: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(tmp_path / "local")
    env["MAIL_AGENT_HEALTH_URL"] = f"http://127.0.0.1:{server.server_port}/health"
    env["MAIL_AGENT_WEB_DIR"] = str(tmp_path / "stale-meipass" / "mail_agent_web")

    # The helper only needs an executable target for this integration test. The synthetic health
    # server represents the newly started packaged gateway and lets CI exercise the real CMD +
    # Windows PowerShell health/version verification path.
    command_line = subprocess.list2cmdline(
        [str(RESTART_HELPER), str(sys.executable), "0.13.8", "no-browser"]
    )
    try:
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command_line],
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert result.returncode == 0, result.stdout + result.stderr
    log = tmp_path / "local" / "Mail-Agent" / "logs" / "update-restart.log"
    assert log.exists()
    assert "Gateway is reachable with expected version 0.13.8" in log.read_text(
        encoding="utf-8", errors="replace"
    )
