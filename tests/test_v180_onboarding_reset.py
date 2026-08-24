from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_reset_is_explicit_safe_and_visible():
    gateway = (ROOT / "apps/gateway/mail_agent_gateway/main_v180.py").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "apps/gateway/mail_agent_gateway/schemas.py").read_text(encoding="utf-8")
    web = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")

    assert 'confirmation: Literal["RESET ONBOARDING"]' in schema
    assert '@base.app.post("/v1/onboarding/reset")' in gateway
    assert 'state["onboarding_completed"] = False' in gateway
    assert 'state.pop("configuration", None)' in gateway
    assert "owner_profile_store.reset()" in gateway
    assert "reset_owner_learning()" in gateway
    assert '"identity_preserved": base.identity_manager.exists()' in gateway
    assert '"operational_history_preserved": True' in gateway
    assert "Onboarding zurücksetzen" in web
    assert "'/v1/onboarding/reset'" in web
    assert "window.confirm" in web
