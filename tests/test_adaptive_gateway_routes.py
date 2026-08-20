from fastapi.testclient import TestClient

from mail_agent_gateway.main_v16 import app


def test_adaptive_routes_remain_reachable_with_web_bundle_mounted():
    client = TestClient(app)

    status = client.get("/v1/adaptive/status")
    privacy = client.get("/v1/usage/privacy")

    assert status.status_code == 200
    assert status.json()["version"] == "0.16.0"
    assert status.json()["privacy"]["usage_contains_mail_content"] is False
    assert privacy.status_code == 200
    assert "usage_events" in privacy.json()["tables"]


def test_web_root_and_assets_mount_remain_available_after_route_reordering():
    client = TestClient(app)
    root = client.get("/")

    assert root.status_code == 200
    assert "<title>MAIL-AGENT</title>" in root.text


def test_named_catch_all_web_mount_is_last_route():
    names = [getattr(route, "name", None) for route in app.router.routes]
    assert names[-1] == "web"
