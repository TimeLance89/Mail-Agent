# Installation

MAIL-AGENT is designed to be installed like a normal desktop application. End users should not need
Python, pip, uvicorn, Git, Docker, or a terminal.

## Windows — recommended

1. Download `Mail-Agent-Setup.exe` from the latest GitHub release.
2. Double-click the installer.
3. Click **Installieren**.
4. Launch **MAIL-AGENT** from the Start menu or optional desktop shortcut.
5. The browser opens automatically and the onboarding begins.

The Windows installer uses a bundled standalone executable. Gateway, local registry development
service, database migrations, web UI, and storage initialization start automatically.

User data is kept outside the installation directory under:

```text
%LOCALAPPDATA%\Mail-Agent
```

Uninstalling the application does not silently delete the user's mailbox data or identity.

## macOS / Linux

The build pipeline also creates standalone binaries that do not require a separate Python
installation. Native signed/notarized packages are planned for the distribution milestone.

## Developer installation

The manual Python setup remains available only for development:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
mail-agent
```

## How the desktop launcher works

The launcher resolves a per-user data directory, starts the required local services, waits for the
gateway health endpoint, and opens `http://127.0.0.1:8765` in the default browser. No service ports
or commands need to be entered by the user.

## Release builds

`.github/workflows/build-installers.yml` creates:

- `Mail-Agent-Setup.exe` for Windows using PyInstaller + Inno Setup
- a standalone binary for macOS
- a standalone binary for Linux

Tagged builds can be published directly as GitHub release assets.
