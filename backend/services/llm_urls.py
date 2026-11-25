"""OpenAI-compatible API URL helpers."""
from urllib.parse import urlsplit, urlunsplit

DEFAULT_API_MODE = "responses"
SUPPORTED_API_MODES = ("responses", "chat_completions")

_ENDPOINT_SUFFIX = {
    "responses": "/responses",
    "chat_completions": "/chat/completions",
}


def normalize_api_mode(api_mode: str) -> str:
    mode = str(api_mode or "").strip().lower()
    return mode if mode in SUPPORTED_API_MODES else DEFAULT_API_MODE


def build_llm_api_url(base_url: str, api_mode: str = DEFAULT_API_MODE) -> str:
    """Build the selected endpoint from a root, /v1 or complete URL."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""

    mode = normalize_api_mode(api_mode)
    suffix = _ENDPOINT_SUFFIX[mode]
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    if not path.endswith(suffix):
        path = f"{path}{suffix}"
    return urlunsplit(
        (parts.scheme, parts.netloc, path, parts.query, parts.fragment)
    )
