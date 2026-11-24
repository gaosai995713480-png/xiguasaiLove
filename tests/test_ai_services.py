import asyncio
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.routers import ai as ai_router
from backend.services.agent_tools import (
    _current_context,
    execute_tool,
    register_tool,
    set_current_user_context,
)
from backend.services.ai_chat import (
    build_anthropic_messages_url,
    build_openai_chat_url,
    split_anthropic_messages,
)


client = TestClient(app)


def _login_admin() -> None:
    token = secrets.token_urlsafe(24)
    _cache_session(token, UserInfo(username="ai_test_admin", role="admin"), time.time() + 3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def test_anthropic_system_prompts_are_joined():
    system, chat = split_anthropic_messages(
        [
            {"role": "system", "content": "context"},
            {"role": "system", "content": "memory"},
            {"role": "system", "content": "skill"},
            {"role": "user", "content": "hello"},
        ]
    )

    assert system == "context\n\nmemory\n\nskill"
    assert chat == [{"role": "user", "content": "hello"}]


def test_openai_url_builder_handles_v1_and_glm_base():
    assert (
        build_openai_chat_url("https://open.bigmodel.cn/api/paas/v4", include_v1=False)
        == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    assert (
        build_openai_chat_url("https://open.bigmodel.cn/api/paas/v4/v1", include_v1=False)
        == "https://open.bigmodel.cn/api/paas/v4/v1/chat/completions"
    )
    assert (
        build_openai_chat_url("https://api.x.ai/v1")
        == "https://api.x.ai/v1/chat/completions"
    )
    assert (
        build_anthropic_messages_url("https://api.anthropic.com/v1")
        == "https://api.anthropic.com/v1/messages"
    )


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


def test_provider_config_can_update_base_url_and_model_without_api_key(monkeypatch):
    _login_admin()
    updates = []
    monkeypatch.setattr(ai_router, "set_config", lambda key, value: updates.append((key, value)))

    response = client.post(
        "/api/ai/config/glm",
        json={"base_url": "https://example.com/api/paas/v4", "model": "glm-test", "api_key": ""},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert updates == [
        (ai_router.GLM_BASE_URL_KEY, "https://example.com/api/paas/v4"),
        (ai_router.GLM_MODEL_KEY, "glm-test"),
    ]


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
