from backend.services.llm_urls import DEFAULT_API_MODE
from backend.tripstar import config as tripstar_config


def _clear_ai_env(monkeypatch):
    for name in (
        "AI_CHAT_API_MODE",
        "AI_CHAT_MODEL",
        "AI_CHAT_API_KEY",
        "AI_CHAT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_tripstar_settings_prefers_shared_db_config(monkeypatch):
    db_values = {
        "AI_CHAT_API_MODE": "chat_completions",
        "AI_CHAT_MODEL": "db-model",
        "AI_CHAT_API_KEY": "db-key",
        "AI_CHAT_BASE_URL": "https://db.example/v1",
    }
    monkeypatch.setattr(tripstar_config, "_db_config", lambda name: db_values.get(name, ""))
    monkeypatch.setenv("AI_CHAT_API_MODE", "responses")
    monkeypatch.setenv("AI_CHAT_MODEL", "env-model")
    monkeypatch.setenv("AI_CHAT_API_KEY", "env-key")
    monkeypatch.setenv("AI_CHAT_BASE_URL", "https://env.example")

    settings = tripstar_config.TripStarSettings()

    assert settings.llm_api_mode == "chat_completions"
    assert settings.llm_model_id == "db-model"
    assert settings.llm_api_key == "db-key"
    assert settings.llm_base_url == "https://db.example/v1"
    assert settings.llm_timeout == 600
    assert settings.has_llm_config is True


def test_tripstar_settings_uses_shared_env_fallback(monkeypatch):
    monkeypatch.setattr(tripstar_config, "_db_config", lambda _name: "")
    monkeypatch.setenv("AI_CHAT_API_MODE", "responses")
    monkeypatch.setenv("AI_CHAT_MODEL", "")
    monkeypatch.setenv("AI_CHAT_API_KEY", "env-key")
    monkeypatch.setenv("AI_CHAT_BASE_URL", "https://env.example/v1")

    settings = tripstar_config.TripStarSettings()

    assert settings.llm_api_mode == "responses"
    assert settings.llm_model_id == ""
    assert settings.llm_api_key == "env-key"
    assert settings.llm_base_url == "https://env.example/v1"
    assert settings.llm_timeout == 600
    assert settings.has_llm_config is True


def test_tripstar_settings_defaults_to_responses_and_optional_model(monkeypatch):
    monkeypatch.setattr(tripstar_config, "_db_config", lambda _name: "")
    _clear_ai_env(monkeypatch)

    settings = tripstar_config.TripStarSettings()

    assert settings.llm_api_mode == DEFAULT_API_MODE == "responses"
    assert settings.llm_model_id == ""
    assert settings.has_llm_config is False


def test_tripstar_settings_normalizes_invalid_api_mode(monkeypatch):
    monkeypatch.setattr(
        tripstar_config,
        "_db_config",
        lambda name: {"AI_CHAT_API_MODE": "something-else"}.get(name, ""),
    )
    _clear_ai_env(monkeypatch)

    settings = tripstar_config.TripStarSettings()

    assert settings.llm_api_mode == "responses"


def test_tripstar_settings_ignores_legacy_llm_config_keys(monkeypatch):
    legacy_db = {
        "TRIPSTAR_LLM_MODEL_ID": "legacy-db-model",
        "TRIPSTAR_LLM_API_KEY": "legacy-db-key",
        "TRIPSTAR_LLM_BASE_URL": "https://legacy-db.example",
        "TRIPSTAR_LLM_TIMEOUT": "999",
        "DEEPSEEK_MODEL": "legacy-deepseek-model",
        "DEEPSEEK_API_KEY": "legacy-deepseek-key",
        "DEEPSEEK_BASE_URL": "https://legacy-deepseek.example",
        "DEEPSEEK_TIMEOUT": "999",
    }
    monkeypatch.setattr(
        tripstar_config,
        "_db_config",
        lambda name: legacy_db.get(name, ""),
    )
    _clear_ai_env(monkeypatch)
    for name, value in legacy_db.items():
        monkeypatch.setenv(name, value)

    settings = tripstar_config.TripStarSettings()

    assert settings.llm_api_mode == "responses"
    assert settings.llm_model_id == ""
    assert settings.llm_api_key == ""
    assert settings.llm_base_url == ""
    assert settings.llm_timeout == 600
    assert settings.has_llm_config is False
