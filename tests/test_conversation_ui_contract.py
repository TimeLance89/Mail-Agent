from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_workbench_exposes_conversation_intelligence():
    source=(ROOT/"apps/web/workbench-ui.js").read_text(encoding="utf-8")
    for token in ["Wartet auf andere","/v1/conversations","data-snooze-thread","cold_outreach_action","follow_up_auto_draft","sender-patterns/accept","decision_path"]:
        assert token in source

def test_015_assets_are_cache_busted():
    html=(ROOT/"apps/web/index.html").read_text(encoding="utf-8")
    assert "?v=0.15.0" in html
    assert "?v=0.14.0" not in html
