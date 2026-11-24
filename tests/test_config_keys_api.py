import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.routers import config as config_router
from backend.tripstar import config as tripstar_config


client = TestClient(app)


@pytest.fixture
def isolated_config_store(monkeypatch):
    store = {}
    monkeypatch.setattr(config_router, "set_config", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(config_router, "get_all_configs", lambda: dict(store))
    return store


def _client_with_role(role: str) -> TestClient:
    local_client = TestClient(app)
    token = secrets.token_urlsafe(24)
    _cache_session(token, UserInfo(username=f"{role}_tester", role=role), time.time() + 3600)
    local_client.cookies.set(SESSION_COOKIE_NAME, token)
    return local_client


def test_admin_can_upsert_generic_config_key_to_love_config(isolated_config_store):
    admin_client = _client_with_role("admin")

    response = admin_client.post(
        "/api/config/keys",
        json={
            "key": "TRIPSTAR_TEST_KEY",
            "value": "unit-test-value",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "key": "TRIPSTAR_TEST_KEY"}
    assert isolated_config_store["TRIPSTAR_TEST_KEY"] == "unit-test-value"


def test_non_admin_cannot_upsert_generic_config_key():
    visitor_client = _client_with_role("visitor")

    response = visitor_client.post(
        "/api/config/keys",
        json={
            "key": "TRIPSTAR_VISITOR_TEST_KEY",
            "value": "should-not-write",
        },
    )

    assert response.status_code == 403


def test_config_key_list_masks_values_for_admin(isolated_config_store):
    admin_client = _client_with_role("admin")
    admin_client.post(
        "/api/config/keys",
        json={"key": "TRIPSTAR_MASK_TEST_KEY", "value": "1234567890abcdef"},
    )

    response = admin_client.get("/api/config/keys")

    assert response.status_code == 200
    payload = response.json()
    item = next(row for row in payload["items"] if row["key"] == "TRIPSTAR_MASK_TEST_KEY")
    assert item["has_value"] is True
    assert item["value"] == ""
    assert item["masked_value"].startswith("1234")
    assert item["masked_value"].endswith("cdef")


def test_tripstar_map_config_reads_frontend_keys_from_love_config_without_leaking_web_key(monkeypatch):
    values = {
        "TRIPSTAR_AMAP_WEB_KEY": "backend-web-key",
        "VITE_TRIPSTAR_AMAP_WEB_JS_KEY": "real-js-key",
        "VITE_TRIPSTAR_AMAP_SECURITY_JS_CODE": "real-security-code",
    }
    monkeypatch.setattr(tripstar_config, "_db_config", lambda name: values.get(name, ""))
    authed = _client_with_role("visitor")

    health_response = authed.get("/api/tripstar/health")
    map_response = authed.get("/api/tripstar/map/config")

    assert health_response.status_code == 200
    assert health_response.json()["amap_configured"] is True
    assert health_response.json()["amap_js_configured"] is True
    assert map_response.status_code == 200
    payload = map_response.json()
    assert payload["configured"] is True
    assert payload["amap_web_js_key"] == "real-js-key"
    assert payload["amap_security_js_code"] == "real-security-code"
    assert "backend-web-key" not in str(payload)
