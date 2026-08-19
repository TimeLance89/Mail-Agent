from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_llm_model_ui_does_not_observe_subtree():
    source = (ROOT / "apps/web/llm-model-settings-v2.js").read_text(encoding="utf-8")
    assert "observer.observe(app, { childList: true });" in source
    assert "subtree: true" not in source


def test_legacy_recursive_model_ui_is_not_loaded():
    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    assert "/assets/llm-model-settings-v2.js" in index
    assert '<script src="/assets/llm-model-settings.js"' not in index
