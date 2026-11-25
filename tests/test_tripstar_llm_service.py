import json

import pytest

from backend.services.llm_urls import (
    DEFAULT_API_MODE,
    build_llm_api_url,
    normalize_api_mode,
)
from backend.tripstar.config import TripStarSettings
from backend.tripstar.services.llm_service import (
    TripStarLLMClient,
    _extract_chat_content,
    _extract_responses_content,
)


def test_extract_chat_content_supports_event_stream_chunks():
    content_type = "text/event-stream"
    body = """
data: {"choices":[{"delta":{"role":"assistant","content":"{\\"ok\\""}}]}

data: {"choices":[{"delta":{"content":": true"}}]}

data: {"choices":[{"delta":{"content":", \\"model\\": \\"grok\\"}"}}]}

data: [DONE]
"""

    assert _extract_chat_content(content_type, body, {}) == '{"ok": true, "model": "grok"}'


def test_extract_responses_content_supports_output_text():
    data = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": '{"ok": '},
                    {"type": "output_text", "text": "true}"},
                ],
            }
        ]
    }

    assert _extract_responses_content("application/json", "", data) == '{"ok": true}'


def test_extract_responses_content_supports_event_stream():
    body = """
data: {"type":"response.output_text.delta","delta":"{\\"ok\\":"}

data: {"type":"response.output_text.delta","delta":" true}"}

data: {"type":"response.completed","response":{"output":[]}}
"""

    assert _extract_responses_content("text/event-stream", body, {}) == '{"ok": true}'


def test_extract_responses_content_supports_completed_fallback():
    body = """
data: {"type":"response.completed","response":{"output":[{"type":"message","content":[{"type":"output_text","text":"{\\"ok\\": true}"}]}]}}
"""

    assert _extract_responses_content("text/event-stream", body, {}) == '{"ok": true}'


@pytest.mark.parametrize(
    ("base_url", "api_mode", "expected"),
    [
        (
            "https://api.example.com",
            "responses",
            "https://api.example.com/responses",
        ),
        (
            "https://api.example.com/v1",
            "responses",
            "https://api.example.com/v1/responses",
        ),
        (
            "https://api.example.com/v1/responses",
            "responses",
            "https://api.example.com/v1/responses",
        ),
        (
            "https://api.example.com",
            "chat_completions",
            "https://api.example.com/chat/completions",
        ),
        (
            "https://api.example.com/v1",
            "chat_completions",
            "https://api.example.com/v1/chat/completions",
        ),
    ],
)
def test_build_llm_api_url(base_url, api_mode, expected):
    assert build_llm_api_url(base_url, api_mode) == expected


def test_api_mode_defaults_to_responses():
    assert DEFAULT_API_MODE == "responses"
    assert normalize_api_mode("") == "responses"
    assert normalize_api_mode("unknown") == "responses"
    assert normalize_api_mode("chat_completions") == "chat_completions"


def _settings(**overrides):
    values = {
        "mock_mode": False,
        "llm_api_mode": "responses",
        "llm_model_id": "",
        "llm_api_key": "demo-key",
        "llm_base_url": "https://llm.example/v1",
    }
    values.update(overrides)
    return TripStarSettings(**values)


def test_llm_client_uses_responses_url_and_omits_empty_model():
    client = TripStarLLMClient(_settings())
    payload = client._payload(system_prompt="system", user_prompt="user")

    assert client.api_url == "https://llm.example/v1/responses"
    assert "model" not in payload
    assert payload["instructions"] == "system"
    assert payload["input"][0] == {"role": "user", "content": "user"}


def test_llm_client_uses_chat_completions_and_configured_model():
    client = TripStarLLMClient(
        _settings(llm_api_mode="chat_completions", llm_model_id="gpt-5.4-codex")
    )
    payload = client._payload(system_prompt="system", user_prompt="user")

    assert client.api_url == "https://llm.example/v1/chat/completions"
    assert payload["model"] == "gpt-5.4-codex"
    assert payload["messages"][0]["role"] == "system"


def test_llm_client_can_run_without_model(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "application/json"}
        text = json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"ok": true}'}],
                    }
                ]
            }
        )

        def raise_for_status(self):
            return None

        def json(self):
            return json.loads(self.text)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.payload = None
            self.url = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            self.url = url
            self.payload = json
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(
        "backend.tripstar.services.llm_service.httpx.Client",
        lambda *args, **kwargs: fake_client,
    )

    result = TripStarLLMClient(_settings()).chat_json(
        system_prompt="system",
        user_prompt="user",
    )

    assert result == {"ok": True}
    assert fake_client.url == "https://llm.example/v1/responses"
    assert "model" not in fake_client.payload
