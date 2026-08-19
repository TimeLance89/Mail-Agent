from __future__ import annotations

import os
import sys
from pathlib import Path

from mail_agent_launcher import main as launcher


def test_frozen_start_replaces_stale_inherited_web_bundle_path(monkeypatch, tmp_path: Path):
    old_bundle = tmp_path / "old-meipass" / "mail_agent_web"
    new_bundle_root = tmp_path / "new-meipass"
    new_bundle = new_bundle_root / "mail_agent_web"
    new_bundle.mkdir(parents=True)
    (new_bundle / "index.html").write_text("<html>MAIL-AGENT</html>", encoding="utf-8")

    monkeypatch.setenv("MAIL_AGENT_WEB_DIR", str(old_bundle))
    monkeypatch.setattr(sys, "_MEIPASS", str(new_bundle_root), raising=False)

    launcher.configure_environment(tmp_path / "data")

    assert os.environ["MAIL_AGENT_WEB_DIR"] == str(new_bundle)
    assert Path(os.environ["MAIL_AGENT_WEB_DIR"]).is_dir()
    assert Path(os.environ["MAIL_AGENT_WEB_DIR"]) != old_bundle


def test_source_start_keeps_explicit_web_override(monkeypatch, tmp_path: Path):
    explicit_web = tmp_path / "custom-web"
    explicit_web.mkdir()
    monkeypatch.setenv("MAIL_AGENT_WEB_DIR", str(explicit_web))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    launcher.configure_environment(tmp_path / "data")

    assert os.environ["MAIL_AGENT_WEB_DIR"] == str(explicit_web)
