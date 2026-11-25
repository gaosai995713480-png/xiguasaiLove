import asyncio
import json
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.routers import ai as ai_router
from backend.services import agent_loop
from backend.services.agent_tools import (
    _current_context,
    execute_tool,
    register_tool,
    set_current_user_context,
)
from backend.services.ai_chat import get_ai_config
from backend.services.llm_urls import (
    build_llm_api_url,
    build_models_api_urls,
    normalize_api_mode,
)


client = TestClient(app)


def _login_admin() -> None:
    token = secrets.token_urlsafe(24)
    _cache_session(
        token,
        UserInfo(username="ai_test_admin", role="admin"),
        time.time() + 3600,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)


def test_api_url_builder_handles_both_modes_and_base_styles():
    assert (
        build_llm_api_url("https://proxy.example.com", "responses")
        == "https://proxy.example.com/responses"
    )
    assert (
        build_llm_api_url("https://proxy.example.com/v1", "responses")
        == "https://proxy.example.com/v1/responses"
    )
    assert (
        build_llm_api_url(
            "https://proxy.example.com/v1/chat/completions",
            "chat_completions",
        )
        == "https://proxy.example.com/v1/chat/completions"
    )
    assert (
        build_llm_api_url(
            "https://proxy.example.com/v1/responses?api-version=2026-01-01",
            "responses",
        )
        == "https://proxy.example.com/v1/responses?api-version=2026-01-01"
    )
    assert normalize_api_mode("") == "responses"
    assert normalize_api_mode("unknown") == "responses"
    assert normalize_api_mode("chat_completions") == "chat_completions"
    assert build_models_api_urls("https://proxy.example.com") == [
        "https://proxy.example.com/models",
        "https://proxy.example.com/v1/models",
    ]
    assert build_models_api_urls(
        "https://proxy.example.com/v1/responses?api-version=2026-01-01"
    ) == [
        "https://proxy.example.com/v1/models?api-version=2026-01-01"
    ]
    assert build_models_api_urls("https://proxy.example.com/v1/models") == [
        "https://proxy.example.com/v1/models"
    ]


def test_ai_config_falls_back_to_environment_and_defaults_to_responses(monkeypatch):
    monkeypatch.setattr("backend.services.ai_chat.get_config", lambda key: "")
    monkeypatch.setenv("AI_CHAT_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_CHAT_API_KEY", "env-key")
    monkeypatch.setenv("AI_CHAT_MODEL", "gpt-5.4-codex")
    monkeypatch.delenv("AI_CHAT_API_MODE", raising=False)

    cfg = get_ai_config()

    assert cfg == {
        "base_url": "https://env.example/v1",
        "api_key": "env-key",
        "model": "gpt-5.4-codex",
        "api_mode": "responses",
    }


def test_ai_config_allows_empty_model(monkeypatch):
    monkeypatch.setattr(
        "backend.services.ai_chat.get_config",
        lambda key: {
            "AI_CHAT_BASE_URL": "https://proxy.example.com/v1",
            "AI_CHAT_API_KEY": "key",
            "AI_CHAT_MODEL": "",
            "AI_CHAT_API_MODE": "chat_completions",
        }.get(key, ""),
    )

    cfg = get_ai_config()

    assert cfg["model"] == ""
    assert cfg["api_mode"] == "chat_completions"


def test_ai_chat_request_limits_history_and_context():
    with pytest.raises(ValidationError):
        ai_router.ChatRequest(
            message="hello",
            history=[{"role": "user", "content": "x"}] * 101,
        )
    with pytest.raises(ValidationError):
        ai_router.ChatRequest(message="hello", client_context="x" * 4001)


def test_conversation_message_batch_is_bounded():
    _login_admin()
    response = client.post(
        "/api/ai/conversations/1/messages",
        json=[{"role": "user", "content": "x"}] * 21,
    )

    assert response.status_code == 422


def test_model_config_can_update_base_url_without_reentering_api_key(monkeypatch):
    _login_admin()
    updates = []
    monkeypatch.setattr(
        ai_router,
        "set_config",
        lambda key, value: updates.append((key, value)),
    )

    response = client.post(
        "/api/ai/config/model",
        json={
            "base_url": "https://proxy.example.com/v1",
            "api_key": "",
            "model": "",
            "api_mode": "responses",
        },
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 3
    assert updates == [
        (ai_router.AI_BASE_URL_KEY, "https://proxy.example.com/v1"),
        (ai_router.AI_MODEL_KEY, ""),
        (ai_router.AI_API_MODE_KEY, "responses"),
    ]


def test_model_config_rejects_unknown_api_mode(monkeypatch):
    _login_admin()
    monkeypatch.setattr(ai_router, "set_config", lambda key, value: None)

    response = client.post(
        "/api/ai/config/model",
        json={"api_mode": "unknown"},
    )

    assert response.status_code == 400


def test_ai_status_exposes_availability_and_mode_only(monkeypatch):
    _login_admin()
    monkeypatch.setattr(
        ai_router,
        "get_ai_config",
        lambda: {
            "base_url": "https://proxy.example.com/v1",
            "api_key": "key",
            "model": "grok-4.20-fast",
            "api_mode": "responses",
        },
    )

    response = client.get("/api/ai/status")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "api_mode": "responses",
    }


def test_model_config_response_keeps_model_but_masks_api_key(monkeypatch):
    _login_admin()
    monkeypatch.setattr(
        ai_router,
        "get_ai_config",
        lambda: {
            "base_url": "https://proxy.example.com/v1",
            "api_key": "sk-1234567890abcdef",
            "model": "gpt-5.4-codex",
            "api_mode": "chat_completions",
        },
    )

    response = client.get("/api/ai/config/model")

    assert response.status_code == 200
    assert response.json() == {
        "base_url": "https://proxy.example.com/v1",
        "api_key_masked": "sk-12345****cdef",
        "api_key_configured": True,
        "model": "gpt-5.4-codex",
        "api_mode": "chat_completions",
    }


def test_model_config_rejects_empty_base_url(monkeypatch):
    _login_admin()
    monkeypatch.setattr(ai_router, "set_config", lambda key, value: None)

    response = client.post(
        "/api/ai/config/model",
        json={"base_url": ""},
    )

    assert response.status_code == 400


def test_model_list_endpoint_uses_form_values_and_root_fallback(monkeypatch):
    _login_admin()
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.payload = payload or {}

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            calls.append({"url": url, "headers": headers})
            if url.endswith("/models") and "/v1/models" not in url:
                return FakeResponse(404)
            return FakeResponse(
                200,
                {
                    "data": [
                        {"id": "gpt-5.4-codex"},
                        {"id": "grok-4.20-fast"},
                        {"id": "gpt-5.4-codex"},
                        {"name": "deepseek-chat"},
                    ]
                },
            )

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = client.post(
        "/api/ai/models",
        json={
            "base_url": "https://proxy.example.com",
            "api_key": "form-key",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            "gpt-5.4-codex",
            "grok-4.20-fast",
            "deepseek-chat",
        ]
    }
    assert [call["url"] for call in calls] == [
        "https://proxy.example.com/models",
        "https://proxy.example.com/v1/models",
    ]
    assert calls[0]["headers"]["Authorization"] == "Bearer form-key"


def test_model_list_endpoint_can_reuse_saved_api_key(monkeypatch):
    _login_admin()
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"models": ["model-a"]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            calls.append({"url": url, "headers": headers})
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        ai_router,
        "get_ai_config",
        lambda: {
            "base_url": "https://saved.example/v1",
            "api_key": "saved-key",
            "model": "",
            "api_mode": "responses",
        },
    )

    response = client.post(
        "/api/ai/models",
        json={"base_url": "", "api_key": ""},
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["model-a"]}
    assert calls[0]["url"] == "https://saved.example/v1/models"
    assert calls[0]["headers"]["Authorization"] == "Bearer saved-key"


def test_model_list_endpoint_requires_admin():
    token = secrets.token_urlsafe(24)
    _cache_session(
        token,
        UserInfo(username="ai_models_visitor", role="visitor"),
        time.time() + 3600,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.post(
        "/api/ai/models",
        json={"base_url": "https://proxy.example.com/v1", "api_key": "key"},
    )

    assert response.status_code == 403


def test_removed_provider_config_routes_are_not_available():
    _login_admin()

    for provider in ("claude", "codex", "glm", "grok", "deepseek"):
        response = client.get(f"/api/ai/config/{provider}")
        assert response.status_code == 404


def test_responses_agent_loop_streams_tools_and_omits_empty_model(monkeypatch):
    register_tool(
        "_audit_responses_echo",
        "echo",
        {"value": {"type": "string"}},
        ["value"],
    )(lambda value: f"echo:{value}")

    streams = [
        [
            'data: {"type":"response.output_text.delta","delta":"思考"}',
            'data: {"type":"response.output_item.added","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"_audit_responses_echo","arguments":""}}',
            'data: {"type":"response.function_call_arguments.delta","item_id":"fc_1","delta":"{\\"value\\":\\"x\\"}"}',
            'data: {"type":"response.output_item.done","item":{"id":"fc_1","type":"function_call","call_id":"call_1","name":"_audit_responses_echo","arguments":"{\\"value\\":\\"x\\"}"}}',
            'data: {"type":"response.completed","response":{"output":[{"id":"msg_1","type":"message","role":"assistant","content":[{"type":"output_text","text":"思考"}]},{"type":"function_call","call_id":"call_1","name":"_audit_responses_echo","arguments":"{\\"value\\":\\"x\\"}"}]}}',
        ],
        [
            'data: {"type":"response.output_text.delta","delta":"完成"}',
            'data: {"type":"response.completed","response":{"output":[{"type":"message","content":[{"type":"output_text","text":"完成"}]}]}}',
        ],
    ]
    calls = []

    class FakeStream:
        def __init__(self, lines):
            self.lines = lines
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            for line in self.lines:
                yield line

        async def aread(self):
            return b""

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, json=None):
            calls.append({"method": method, "url": url, "headers": headers, "body": json})
            return FakeStream(streams.pop(0))

    monkeypatch.setattr(agent_loop.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_loop,
        "get_config",
        lambda key: "5" if key == "AGENT_MAX_TOOL_ROUNDS" else "true",
    )

    async def run():
        chunks = []
        async for chunk in agent_loop.ai_agent_loop(
            "https://proxy.example.com/v1",
            "key",
            "",
            "responses",
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hi"},
            ],
        ):
            chunks.append(json.loads(chunk))
        return chunks

    chunks = asyncio.run(run())
    assert "思考" in chunks
    assert "完成" in chunks
    assert not any(
        isinstance(item, dict)
        and item.get("type") in {"tool_call", "tool_result"}
        for item in chunks
    )
    assert calls[0]["url"] == "https://proxy.example.com/v1/responses"
    assert "model" not in calls[0]["body"]
    assert calls[0]["body"]["instructions"] == "system"
    assert any(
        tool.get("name") == "_audit_responses_echo"
        for tool in calls[0]["body"]["tools"]
    )
    assert calls[1]["body"]["input"][-1]["type"] == "function_call_output"
    assert calls[1]["body"]["input"][-1]["output"] == "echo:x"


def test_chat_completions_agent_loop_omits_empty_model(monkeypatch):
    streams = [[
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        "data: [DONE]",
    ]]
    calls = []

    class FakeStream:
        status_code = 200
        headers = {}

        def __init__(self, lines):
            self.lines = lines

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            for line in self.lines:
                yield line

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, json=None):
            calls.append({"url": url, "body": json})
            return FakeStream(streams.pop(0))

    monkeypatch.setattr(agent_loop.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_loop,
        "get_config",
        lambda key: "5" if key == "AGENT_MAX_TOOL_ROUNDS" else "true",
    )

    async def run():
        chunks = []
        async for chunk in agent_loop.ai_agent_loop(
            "https://proxy.example.com/v1",
            "key",
            "",
            "chat_completions",
            [{"role": "user", "content": "hi"}],
        ):
            chunks.append(json.loads(chunk))
        return chunks

    assert asyncio.run(run()) == ["你好"]
    assert calls[0]["url"] == "https://proxy.example.com/v1/chat/completions"
    assert "model" not in calls[0]["body"]


def test_responses_agent_loop_accepts_non_streaming_json(monkeypatch):
    calls = []

    class FakeStream:
        status_code = 200
        headers = {"content-type": "application/json"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aread(self):
            return json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "JSON 回复"}],
                        }
                    ]
                }
            ).encode()

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, json=None):
            calls.append({"url": url, "body": json})
            return FakeStream()

    monkeypatch.setattr(agent_loop.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_loop,
        "get_config",
        lambda key: "5" if key == "AGENT_MAX_TOOL_ROUNDS" else "true",
    )

    async def run():
        return [
            json.loads(chunk)
            async for chunk in agent_loop.ai_agent_loop(
                "https://proxy.example.com/v1",
                "key",
                "gpt-5.4-codex",
                "responses",
                [{"role": "user", "content": "hi"}],
            )
        ]

    assert asyncio.run(run()) == ["JSON 回复"]
    assert calls[0]["body"]["model"] == "gpt-5.4-codex"


def test_execute_tool_does_not_block_event_loop():
    register_tool("_audit_slow_tool", "slow", {}, [])(lambda: time.sleep(0.15) or "ok")

    async def ticker():
        started = time.perf_counter()
        await asyncio.sleep(0.02)
        return time.perf_counter() - started

    async def run():
        tick_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        result = await execute_tool("_audit_slow_tool", {})
        tick_delay = await tick_task
        return result, tick_delay

    result, tick_delay = asyncio.run(run())

    assert result == "ok"
    assert tick_delay < 0.12


def test_execute_tool_preserves_permission_context():
    register_tool("_audit_context_tool", "context", {}, [])(
        lambda: f"{_current_context.get().username}:{_current_context.get().is_admin}"
    )
    set_current_user_context("context_user", "admin", True)

    result = asyncio.run(execute_tool("_audit_context_tool", {}))

    assert result == "context_user:True"
