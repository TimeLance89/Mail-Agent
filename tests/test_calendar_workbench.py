from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "apps/web/calendar-workbench.js"
MAIL_SUGGESTIONS = ROOT / "apps/web/calendar-mail-suggestions.js"
V171_UX = ROOT / "apps/web/v171-ux.js"
V172_UX = ROOT / "apps/web/v172-ux.js"


def test_calendar_workbench_is_loaded_and_cache_busted():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/calendar-ui.js?v=0.17.3" in index
    assert "/assets/calendar-workbench.js?v=0.17.3" in index
    assert "/assets/calendar-mail-suggestions.js?v=0.17.3" in index
    assert "/assets/v171-ux.js?v=0.17.3" in index
    assert "/assets/v172-ux.js?v=0.17.3" in index
    assert index.index("/assets/calendar-workbench.js?v=0.17.3") < index.index(
        "/assets/calendar-mail-suggestions.js?v=0.17.3"
    )
    assert index.index("/assets/dashboard-live.js?v=0.17.3") < index.index(
        "/assets/v171-ux.js?v=0.17.3"
    )
    assert index.index("/assets/v171-ux.js?v=0.17.3") < index.index(
        "/assets/v172-ux.js?v=0.17.3"
    )


def test_calendar_is_a_first_class_view_with_mail_bridge():
    source = CALENDAR.read_text(encoding="utf-8")
    assert "activeView === 'calendar'" in source
    assert 'data-view="calendar"' in source
    assert "Mit Kalender planen" in source
    assert "Freie Zeiten antworten" in source
    assert "/v1/calendar/mail-reply" in source
    desktop = (ROOT / "apps/web/desktop-links.js").read_text(encoding="utf-8")
    assert "'calendar'" in desktop


def test_v171_calendar_prioritizes_outcome_over_controls():
    source = V171_UX.read_text(encoding="utf-8")
    assert "Was soll ich für dich erledigen?" in source
    assert "Prüfen & vorbereiten" in source
    assert "Terminanfragen aus deinen Mails" in source
    assert "Der konkrete angefragte Zeitpunkt wird zuerst geprüft" in source
    assert "Optionen & Details" in source
    assert "Freie Zeiten" not in source or "3 freie Zeiten finden" in source


def test_v172_exposes_discard_in_actual_workbench_and_calendar_confirmation_handoff():
    source = V172_UX.read_text(encoding="utf-8")
    assert "exposeWorkbenchDiscard" in source
    assert "data.draftDiscard" in source or "draftDiscard" in source
    assert "/v1/drafts/${encodeURIComponent(draftId)}/discard" in source
    assert "Ablehnen & verwerfen" in source
    assert "Entwurf verworfen." in source
    assert "prepare-mail-reply" in source
    assert "Bestätigungsantwort ist vorbereitet" in source
    assert "Freigaben" in source
    assert "Freigeben & senden" in source


def test_calendar_mail_suggestions_endpoint_remains_side_effect_free_and_actionable():
    source = MAIL_SUGGESTIONS.read_text(encoding="utf-8")
    assert "/v1/calendar/mail-suggestions" in source
    assert "Mail-Inhalte bleiben untrusted" in source
    assert "Mit Kalender prüfen" in source


def test_shared_writer_without_private_access_is_not_labeled_readonly():
    source = MAIL_SUGGESTIONS.read_text(encoding="utf-8")
    gateway = (ROOT / "apps/gateway/mail_agent_gateway/main_v172.py").read_text(encoding="utf-8")
    assert "writerwithoutprivateaccess" in source
    assert "correctSharedCalendarRoleLabels" in source
    assert "writerwithoutprivateaccess" in gateway
    assert "_ensure_writable_calendar_v172" in gateway


def test_v171_errors_stay_visible_and_preserve_calendar_diagnostics():
    source = V171_UX.read_text(encoding="utf-8")
    assert "12000" in source
    assert "403 forbidden" in source.lower()
    assert "Google Kalender hat den Zugriff verweigert" in source


def test_calendar_workbench_has_no_recursive_dom_observer():
    for path in (CALENDAR, MAIL_SUGGESTIONS, V171_UX, V172_UX):
        source = path.read_text(encoding="utf-8")
        assert "MutationObserver" not in source
        assert "subtree: true" not in source


def test_calendar_javascript_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available")
    for path in (CALENDAR, MAIL_SUGGESTIONS, V171_UX, V172_UX):
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
