from backend.config import settings
from backend.routers import weather as weather_router
from backend.services import gaode


def test_gaode_key_prefers_weather_database_value(monkeypatch):
    values = {
        "AMAP_KEY": "weather-db-key",
        "TRIPSTAR_AMAP_WEB_KEY": "tripstar-db-key",
    }
    monkeypatch.setattr(gaode, "get_config", values.get)
    monkeypatch.setattr(settings, "gaode_key", "env-key")

    assert gaode.resolve_gaode_key() == "weather-db-key"


def test_gaode_key_falls_back_to_tripstar_database_value(monkeypatch):
    values = {"TRIPSTAR_AMAP_WEB_KEY": "tripstar-db-key"}
    monkeypatch.setattr(gaode, "get_config", values.get)
    monkeypatch.setattr(settings, "gaode_key", "env-key")

    assert gaode.resolve_gaode_key() == "tripstar-db-key"


def test_gaode_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setattr(gaode, "get_config", lambda _key: "")
    monkeypatch.setattr(settings, "gaode_key", "env-key")

    assert gaode.resolve_gaode_key() == "env-key"


def test_weather_route_uses_resolved_database_key(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_router, "resolve_gaode_key", lambda: "resolved-key")
    monkeypatch.setattr(
        weather_router,
        "proxy_gaode",
        lambda url, params, key: calls.append((url, params, key)) or {"status": "1"},
    )

    assert weather_router.weather(city="420100", extensions="base", _=None) == {
        "status": "1"
    }
    assert calls[0][2] == "resolved-key"
