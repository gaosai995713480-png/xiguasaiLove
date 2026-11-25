"""Configuration for the single OpenAI-compatible AI endpoint."""
import os

from ..database import get_config
from .llm_urls import DEFAULT_API_MODE, normalize_api_mode

AI_BASE_URL_KEY = "AI_CHAT_BASE_URL"
AI_API_KEY_KEY = "AI_CHAT_API_KEY"
AI_MODEL_KEY = "AI_CHAT_MODEL"
AI_API_MODE_KEY = "AI_CHAT_API_MODE"


def _config_or_env(key: str) -> str:
    db_value = (get_config(key) or "").strip()
    return db_value or os.getenv(key, "").strip()


def get_ai_config() -> dict:
    """Resolve the endpoint from the database, then environment."""
    return {
        "base_url": _config_or_env(AI_BASE_URL_KEY),
        "api_key": _config_or_env(AI_API_KEY_KEY),
        "model": _config_or_env(AI_MODEL_KEY),
        "api_mode": normalize_api_mode(
            _config_or_env(AI_API_MODE_KEY) or DEFAULT_API_MODE
        ),
    }


def is_ai_configured(config: dict | None = None) -> bool:
    cfg = config or get_ai_config()
    return bool(cfg["base_url"] and cfg["api_key"])
