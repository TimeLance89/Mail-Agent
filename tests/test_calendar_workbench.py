from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "apps/web/calendar-workbench.js"
MAIL_SUGGESTIONS = ROOT / "apps/web/calendar-mail-suggestions.js"


def test_calendar_workbench_is_loaded_and_cache_busted():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/calendar-ui.js?v=0.17.0" in index
    assert "/assets/calendar-workbench.js?v=0.17.0" in index
    assert "/assets/calendar-mail-suggestions.js?v=0.17.0" in index
    assert index.index("/assets/workbench-ui.js?v=0.17.0") < index.index(
        "/assets/calendar-workbench.js?v=0.17.0"
    )
    assert index.index("/assets/calendar-workbench.js?v=0.17.0") < index.index(
        "/assets/calendar-mail-suggestions.js?v=0.17.0"
    )


def test_calendar_is_a_first_class_view_with_mail_bridge():
    source = CALENDAR.read_text(encoding="utf-8")
    assert "activeView === 'calendar'" in source
    assert 'data-view="calendar"' in source
    assert "Mit Kalender planen" in source
    assert "Freie Zeiten antworten" in source
    assert "/v1/calendar/mail-reply" in source
    assert "source_message_id:cal.sourceMessageId" in source
    desktop = (ROOT / "apps/web/desktop-links.js").read_text(encoding="utf-8")
    assert "'calendar'" in desktop


def test_calendar_workbench_exposes_real_assistance_flows():
    source = CALENDAR.read_text(encoding="utf-8")
    for endpoint in (
        "/v1/calendar/briefing",
        "/v1/calendar/free-slots",
        "/v1/calendar/concierge",
        "/v1/calendar/proposals",
        "/v1/calendar/approvals/",
    ):
        assert endpoint in source
    assert "Deterministisch aus Google Free/Busy" in source
    assert "Bei fehlenden Angaben fragt der Agent nach" in source
    assert "Google-Einladungen werden versendet" in source


def test_calendar_mail_suggestions_are_actionable_but_side_effect_free_until_user_action():
    source = MAIL_SUGGESTIONS.read_text(encoding="utf-8")
    assert "/v1/calendar/mail-suggestions" in source
    assert "Terminwünsche aus E-Mails" in source
    assert "Mail-Inhalte bleiben untrusted" in source
    assert "Mit Kalender prüfen" in source
    assert "Freie Zeiten antworten" in source


def test_calendar_connect_opens_popup_before_async_oauth_start():
    source = CALENDAR.read_text(encoding="utf-8")
    popup = source.index("window.open('about:blank'")
    start = source.index("/v1/oauth/google/calendar/start")
    assert popup < start


def test_calendar_workbench_has_no_recursive_dom_observer_or_poll_loop():
    for path in (CALENDAR, MAIL_SUGGESTIONS):
        source = path.read_text(encoding="utf-8")
        assert "MutationObserver" not in source
        assert "setInterval" not in source
        assert "subtree: true" not in source


def test_calendar_workbench_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    for path in (CALENDAR, MAIL_SUGGESTIONS):
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
