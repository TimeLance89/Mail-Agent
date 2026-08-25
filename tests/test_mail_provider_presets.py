from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_provider_setup_is_loaded_and_versioned():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/mail-provider-setup.css?v=0.18.2" in index
    assert "/assets/mail-provider-setup.js?v=0.18.2" in index
    assert "app.js?v=0.18.2" in index


def test_provider_setup_javascript_syntax():
    node = shutil.which("node")
    if node:
        subprocess.run(
            [node, "--check", str(ROOT / "apps/web/mail-provider-setup.js")],
            check=True,
            capture_output=True,
            text=True,
        )


def test_common_provider_presets_are_available():
    source = (ROOT / "apps/web/mail-provider-setup.js").read_text(encoding="utf-8")
    for provider in (
        "Gmail / Google Workspace",
        "Outlook / Microsoft 365",
        "GMX",
        "WEB.DE",
        "Yahoo Mail",
        "Apple iCloud Mail",
        "IONOS",
        "STRATO",
        "Telekom Mail",
        "mailbox.org",
        "Fastmail",
        "Anderer Anbieter",
    ):
        assert provider in source
    assert "imap.gmx.net" in source
    assert "imap.web.de" in source
    assert "imap.mail.yahoo.com" in source
    assert "imap.mail.me.com" in source
    assert "imap.ionos.de" in source
    assert "imap.strato.de" in source
    assert "secureimap.t-online.de" in source
    assert "imap.mailbox.org" in source
    assert "imap.fastmail.com" in source


def test_provider_setup_auto_detects_and_keeps_advanced_fallback():
    source = (ROOT / "apps/web/mail-provider-setup.js").read_text(encoding="utf-8")
    assert "function detectProvider" in source
    assert "Automatisch erkannt:" in source
    assert "Erweiterte Serverdaten anzeigen" in source
    assert "Postfach verbinden" in source
    assert "provider-oauth-action" in source
    assert "nativeOAuth(provider)?.click()" in source
    assert "new MutationObserver(() => enhanceSetup()).observe(app, {childList:true})" in source
    assert "subtree:true" not in source
    assert "subtree: true" not in source


def test_password_guidance_for_app_password_providers():
    source = (ROOT / "apps/web/mail-provider-setup.js").read_text(encoding="utf-8")
    assert "Yahoo verlangt" in source
    assert "iCloud benötigt ein app-spezifisches Passwort" in source
    assert "Fastmail verlangt" in source
    assert "Passwort für E-Mail-Programme" in source
