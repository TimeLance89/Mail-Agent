# Installation

MAIL-AGENT is installed like a normal desktop application. End users do not need Python, pip,
uvicorn, Git, Docker, GitHub Actions, a terminal, or knowledge about local service ports.

## Windows — end-user installation

1. Open the MAIL-AGENT Preview release page.
2. Download **`Mail-Agent-Setup.exe`** directly.
3. Double-click the downloaded file.
4. Click **Installieren**.
5. Start **MAIL-AGENT** from the Start menu or desktop shortcut.
6. MAIL-AGENT starts its local services automatically and opens the onboarding.

There is no ZIP extraction and no GitHub Actions workflow involved in the end-user path.

The preview release uses the fixed tag `preview-latest`. Every successful build from `main` replaces
the installer on that release, so testers always have one stable place to obtain the current setup.

The Windows installer contains the standalone MAIL-AGENT application. Gateway, local registry
service, database migrations, web UI, storage initialization, and health checks are started
implicitly by the desktop launcher.

User data is kept outside the installation directory under:

```text
%LOCALAPPDATA%\Mail-Agent
```

Uninstalling the application does not silently delete the user's mailbox data or agent identity.

## Public distribution target

The private repository is a development and test channel. A public product release should expose the
same installer through a normal product download page, so users only see a **Download for Windows**
button and never need a GitHub account.

## macOS / Linux

The build pipeline also creates standalone binaries that do not require a separate Python
installation. Native signed/notarized packages are planned for the distribution milestone.

## Developer installation

The manual Python setup is development-only:

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

## Automated builds

`.github/workflows/build-installers.yml` creates:

- `Mail-Agent-Setup.exe` for Windows using PyInstaller + Inno Setup
- a standalone binary for macOS
- a standalone binary for Linux

Every successful `main` build updates the `preview-latest` prerelease with direct downloadable
binaries. Version tags (`v*`) continue to create normal versioned releases.
