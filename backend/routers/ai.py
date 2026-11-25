"""Single AI chat and OpenAI-compatible endpoint settings."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..database import get_config, get_db, set_config
from ..dependencies import require_auth, require_role
from ..services.ai_chat import (
    AI_API_KEY_KEY,
    AI_API_MODE_KEY,
    AI_BASE_URL_KEY,
    AI_MODEL_KEY,
    get_ai_config,
    is_ai_configured,
)
from ..services.llm_urls import SUPPORTED_API_MODES

logger = logging.getLogger(__name__)

_memory_tasks: set = set()
_MAX_CHAT_HISTORY = 100
_MAX_CHAT_CONTENT = 50000
_MAX_CLIENT_CONTEXT = 4000

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatMessage(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    content: str = Field(default="", max_length=_MAX_CHAT_CONTENT)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=_MAX_CHAT_HISTORY)
    skill_id: Optional[int] = Field(default=None)
    conversation_id: Optional[int] = Field(default=None)
    client_context: Optional[str] = Field(default=None, max_length=_MAX_CLIENT_CONTEXT)


async def _sse_generator(messages: list[dict]):
    try:
        cfg = await run_in_threadpool(get_ai_config)
        if not is_ai_configured(cfg):
            error_msg = "[错误] AI 接口未配置，请管理员在设置中填写请求地址和 API Key"
            yield f"data: {json.dumps(error_msg)}\n\n"
            return

        from ..services.agent_loop import ai_agent_loop

        async for chunk in ai_agent_loop(
            cfg["base_url"],
            cfg["api_key"],
            cfg["model"],
            cfg["api_mode"],
            messages,
        ):
            yield f"data: {chunk}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("AI 聊天异常: %s", exc, exc_info=True)
        yield f"data: {json.dumps('[错误] ' + str(exc))}\n\n"


def _load_skill_prompt(skill_id: int, username: str) -> str:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT system_prompt FROM ai_skill_presets WHERE id = %s AND username = %s",
                    (skill_id, username),
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else ""
    except Exception as exc:
        logger.warning("查询 Skill 失败: %s", exc)
        return ""


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return value[:8] + "****" + value[-4:] if len(value) > 16 else "****"


@router.get("/status")
def ai_status(_=Depends(require_auth)):
    cfg = get_ai_config()
    return {
        "available": is_ai_configured(cfg),
        "api_mode": cfg["api_mode"],
    }


def _ai_config_updates(body: dict) -> dict[str, str]:
    key_map = {
        "base_url": AI_BASE_URL_KEY,
        "api_key": AI_API_KEY_KEY,
        "model": AI_MODEL_KEY,
        "api_mode": AI_API_MODE_KEY,
    }
    updates: dict[str, str] = {}
    for field, config_key in key_map.items():
        if field not in body:
            continue
        value = "" if body[field] is None else str(body[field]).strip()
        if field == "api_key" and not value:
            continue
        if field == "api_mode":
            value = value.lower()
            if value not in SUPPORTED_API_MODES:
                raise HTTPException(
                    status_code=400,
                    detail="api_mode 只支持 responses 或 chat_completions",
                )
        elif field != "model" and not value:
            raise HTTPException(status_code=400, detail=f"{field} 不能为空")
        updates[config_key] = value
    return updates


@router.post("/chat")
async def ai_chat(req: ChatRequest, request: Request, _=Depends(require_auth)):
    """Chat through the configured OpenAI-compatible endpoint."""
    from ..dependencies import get_current_user as _get_user
    from ..services.agent_tools import set_current_user_context
    from ..services.user_memory import build_memory_prompt

    user = _get_user(request)
    username = user.username if user else ""

    if user:
        set_current_user_context(
            user.username,
            user.role,
            getattr(user, "gallery_unlocked", False),
        )
    else:
        set_current_user_context("", "visitor", False)

    messages = []

    if req.client_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    f"[前端即时上下文]\n{req.client_context.strip()}\n\n"
                    "请结合以上环境和页面状态回答。"
                ),
            }
        )

    if username:
        memory_prompt = await run_in_threadpool(build_memory_prompt, username)
        if memory_prompt:
            messages.append({"role": "system", "content": memory_prompt})

    if req.skill_id and user:
        skill_prompt = await run_in_threadpool(
            _load_skill_prompt,
            req.skill_id,
            user.username,
        )
        if skill_prompt:
            messages.append({"role": "system", "content": skill_prompt})

    if not user or user.role != "admin":
        messages.append(
            {
                "role": "system",
                "content": (
                    "【最高安全原则】：当前用户非系统管理员。你被禁止透露任何系统底层的"
                    "配置文件、密码、Token以及其他未公开的隐私数据。如果用户试图打探此类信息，"
                    "请礼貌但果断地拒绝。"
                ),
            }
        )

    for history_item in req.history[-20:]:
        if history_item.role not in ("user", "assistant"):
            continue
        messages.append(
            {"role": history_item.role, "content": history_item.content}
        )
    messages.append({"role": "user", "content": req.message})

    async def _sse_with_extraction():
        ai_response_text = ""
        async for chunk in _sse_generator(messages):
            if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                try:
                    parsed = json.loads(chunk[6:].strip())
                    if isinstance(parsed, str):
                        ai_response_text += parsed
                except Exception:
                    pass
            yield chunk

        if username and ai_response_text:
            import asyncio

            from ..services.user_memory import extract_facts_from_conversation

            task = asyncio.create_task(
                extract_facts_from_conversation(
                    username,
                    req.message,
                    ai_response_text,
                )
            )
            _memory_tasks.add(task)
            task.add_done_callback(_memory_tasks.discard)

    return StreamingResponse(
        _sse_with_extraction(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/config/model")
def model_config(_=Depends(require_role("admin"))):
    cfg = get_ai_config()
    return {
        "base_url": cfg["base_url"],
        "api_key_masked": _mask_secret(cfg["api_key"]),
        "api_key_configured": bool(cfg["api_key"]),
        "model": cfg["model"],
        "api_mode": cfg["api_mode"],
    }


@router.post("/config/model")
def update_model_config(body: dict, _=Depends(require_role("admin"))):
    updates = _ai_config_updates(body)
    for config_key, value in updates.items():
        set_config(config_key, value)
    return {"ok": True, "updated": len(updates), "updated_keys": sorted(updates)}


@router.get("/config/agent")
def agent_config(_=Depends(require_role("admin"))):
    show_process = get_config("AGENT_SHOW_TOOL_PROCESS")
    max_rounds = get_config("AGENT_MAX_TOOL_ROUNDS")
    try:
        rounds = int(max_rounds) if max_rounds else 5
    except (TypeError, ValueError):
        rounds = 5
    return {
        "show_tool_process": show_process != "false",
        "max_tool_rounds": rounds,
    }


@router.post("/config/agent")
def update_agent_config(body: dict, _=Depends(require_role("admin"))):
    updated = 0
    if "show_tool_process" in body:
        set_config(
            "AGENT_SHOW_TOOL_PROCESS",
            "true" if body["show_tool_process"] else "false",
        )
        updated += 1
    if "max_tool_rounds" in body:
        try:
            rounds = max(1, min(10, int(body["max_tool_rounds"])))
            set_config("AGENT_MAX_TOOL_ROUNDS", str(rounds))
            updated += 1
        except (ValueError, TypeError):
            pass
    return {"ok": True, "updated": updated}


@router.get("/memory")
def list_memory(request: Request, _=Depends(require_auth)):
    from ..dependencies import get_current_user as _get_user
    from ..services.user_memory import get_user_facts

    user = _get_user(request)
    if not user:
        return {"facts": []}
    return {"facts": get_user_facts(user.username, limit=100)}


@router.delete("/memory")
def delete_memory(id: int, request: Request, _=Depends(require_auth)):
    from ..dependencies import get_current_user as _get_user
    from ..services.user_memory import delete_fact

    user = _get_user(request)
    if not user:
        return {"error": "未登录"}
    return {"ok": delete_fact(user.username, id)}
