from fastapi.testclient import TestClient

from mail_agent_gateway.main_v180 import app


def test_adaptive_calendar_and_draft_routes_remain_reachable_with_web_bundle_mounted():
    client = TestClient(app)

    status = client.get("/v1/adaptive/status")
    privacy = client.get("/v1/usage/privacy")
    calendar = client.get("/v1/calendar/status")

    assert status.status_code == 200
    assert status.json()["version"] == "0.18.2"
    assert status.json()["privacy"]["usage_contains_mail_content"] is False
    assert privacy.status_code == 200
    assert "usage_events" in privacy.json()["tables"]
    assert calendar.status_code == 200
    assert calendar.json()["write_requires_approval"] is True
    assert calendar.json()["direct_write_allowed"] is False
    assert "autonomous_safe_create_allowed" in calendar.json()


def test_calendar_and_draft_lifecycle_routes_are_exposed_in_openapi():
    client = TestClient(app)
    paths = client.get("/openapi.json").json()["paths"]
    for route in (
        "/v1/oauth/google/calendar/start",
        "/v1/calendar/status",
        "/v1/calendar/calendars",
        "/v1/calendar/events",
        "/v1/calendar/freebusy",
        "/v1/calendar/proposals",
        "/v1/calendar/approvals",
        "/v1/calendar/approvals/{approval_id}/approve",
        "/v1/calendar/approvals/{approval_id}/reject",
        "/v1/calendar/approvals/{approval_id}/prepare-mail-reply",
        "/v1/drafts/{draft_id}/discard",
        "/v1/briefing",
        "/v1/onboarding/reset",
    ):
        assert route in paths


def test_web_root_and_assets_mount_remain_available_after_route_reordering():
    client = TestClient(app)
    root = client.get("/")

    assert root.status_code == 200
    assert "<title>MAIL-AGENT</title>" in root.text
    assert "/assets/calendar-ui.js?v=0.18.2" in root.text
    assert "/assets/v171-ux.js?v=0.18.2" in root.text
    assert "/assets/v172-ux.js?v=0.18.2" in root.text


def test_named_catch_all_web_mount_is_last_route():
    names = [getattr(route, "name", None) for route in app.router.routes]
    assert names[-1] == "web"
