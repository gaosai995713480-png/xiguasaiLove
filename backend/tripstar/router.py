"""TripStar API 路由。"""
from __future__ import annotations

import asyncio
import time
import traceback
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, WebSocket
from starlette.concurrency import run_in_threadpool

from ..dependencies import SESSION_COOKIE_NAME, UserInfo, get_current_user, get_user_from_token
from .config import get_tripstar_settings
from .models.schemas import TripStarRequest, TripStarRouteRequest, TripStarSubmitResponse
from .planner import TripStarPlanner
from .services.amap_service import AmapService, AmapServiceError
from .services.xhs_service import XhsCookieExpiredError, XhsService, XhsServiceError
from .task_store import TripStarTaskStore

router = APIRouter(prefix="/api/tripstar", tags=["TripStar 旅行智能体"])

_PLACEHOLDER_CONFIG_VALUES = {
    "frontend-js-key",
    "web-js-key",
    "security-code",
    "your-key",
    "your-amap-key",
    "your-amap-web-js-key",
    "your-amap-security-js-code",
    "test-key",
}


def _new_store() -> TripStarTaskStore:
    settings = get_tripstar_settings()
    stale_after = max(45 * 60, int(settings.llm_timeout) * 2 + 5 * 60)
    return TripStarTaskStore(settings.task_dir, stale_after_seconds=stale_after)


_store = _new_store()


def _require_user(request: Request) -> UserInfo:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def _can_view_task(user: UserInfo, task: dict, include_all: bool = False) -> bool:
    return task.get("owner") == user.username or (include_all and user.role == "admin")


def _websocket_timeout_seconds(settings) -> float:
    # LLM 失败会重试一次，并可能在之后继续做 POI/路线请求。
    return max(300.0, float(settings.llm_timeout) * 2 + 120.0)


def _is_placeholder_config(value: str) -> bool:
    return str(value or "").strip().lower() in _PLACEHOLDER_CONFIG_VALUES


def _usable_config_value(value: str) -> str:
    value = str(value or "").strip()
    return "" if _is_placeholder_config(value) else value


def _serialize_task(task: dict) -> dict:
    return {
        "task_id": task.get("task_id"),
        "plan_id": task.get("plan_id", task.get("task_id")),
        "owner": task.get("owner", ""),
        "status": task.get("status", "processing"),
        "stage": task.get("stage", ""),
        "progress": task.get("progress", 0),
        "message": task.get("message", ""),
        "result": task.get("result"),
        "error": task.get("error"),
        "request_payload": task.get("request_payload") if task.get("status") == "failed" else None,
    }


def _run_task(task_id: str, request_payload: dict) -> None:
    def progress(stage: str, message: str, value: int) -> None:
        _store.update(
            task_id,
            status="processing",
            stage=stage,
            progress=value,
            message=message,
        )

    try:
        settings = get_tripstar_settings()
        planner = TripStarPlanner(settings)
        request = TripStarRequest(**request_payload)
        result = planner.plan(request, progress)
        _store.update(
            task_id,
            status="completed",
            stage="completed",
            progress=100,
            message=result.get("message") or "旅行计划生成成功",
            result=result,
            error=None,
        )
    except Exception as exc:
        traceback.print_exc()
        _store.update(
            task_id,
            status="failed",
            stage="failed",
            progress=100,
            message=str(exc),
            error=str(exc),
        )


@router.get("/health", summary="TripStar 健康检查")
def health_check():
    settings = get_tripstar_settings()
    amap_js_configured = bool(
        _usable_config_value(settings.amap_web_js_key)
        and _usable_config_value(settings.amap_security_js_code)
    )
    return {
        "status": "healthy" if settings.enabled else "disabled",
        "service": "tripstar",
        "mock_mode": settings.effective_mock_mode,
        "has_llm_config": settings.has_llm_config,
        "xhs_enabled": settings.enable_xhs and bool(settings.xhs_cookie),
        "amap_configured": bool(settings.amap_web_key),
        "amap_js_configured": amap_js_configured,
        "google_maps_configured": bool(settings.google_maps_api_key),
        "task_store": "ready" if _store.ready() else "unavailable",
    }


@router.get("/map/config", summary="获取 TripStar 前端地图配置")
def get_map_config(_user: UserInfo = Depends(_require_user)):
    settings = get_tripstar_settings()
    amap_web_js_key = _usable_config_value(settings.amap_web_js_key)
    amap_security_js_code = _usable_config_value(settings.amap_security_js_code)
    issues = []
    if not amap_web_js_key:
        issues.append("VITE_TRIPSTAR_AMAP_WEB_JS_KEY 未配置或仍是占位值")
    if not amap_security_js_code:
        issues.append("VITE_TRIPSTAR_AMAP_SECURITY_JS_CODE 未配置或仍是占位值")
    configured = not issues
    return {
        "provider": "amap",
        "configured": configured,
        "amap_web_js_key": amap_web_js_key if configured else "",
        "amap_security_js_code": amap_security_js_code if configured else "",
        "message": "" if configured else "；".join(issues),
        "issues": issues,
    }


def _amap_service() -> AmapService:
    settings = get_tripstar_settings()
    if not settings.amap_web_key:
        raise HTTPException(status_code=503, detail="TripStar 高德 Web 服务 Key 未配置")
    return AmapService(settings.amap_web_key)


def _map_error(exc: AmapServiceError) -> HTTPException:
    message = str(exc) or "TripStar 地图服务调用失败"
    if "Key 未配置" in message:
        return HTTPException(status_code=503, detail=message)
    return HTTPException(status_code=502, detail=message)


def _xhs_service() -> XhsService:
    settings = get_tripstar_settings()
    if not settings.enable_xhs:
        raise HTTPException(status_code=503, detail="TripStar 小红书功能未启用")
    if not settings.xhs_cookie:
        raise HTTPException(status_code=503, detail="TripStar 小红书 Cookie 未配置")
    return XhsService(settings.xhs_cookie)


@router.get("/xhs/status", summary="TripStar 小红书配置状态")
def get_xhs_status(_user: UserInfo = Depends(_require_user)):
    settings = get_tripstar_settings()
    cookie_length = len(settings.xhs_cookie or "")
    return {
        "enabled": bool(settings.enable_xhs),
        "configured": bool(settings.enable_xhs and settings.xhs_cookie),
        "has_cookie": bool(settings.xhs_cookie),
        "cookie_length": cookie_length,
    }


@router.get("/xhs/search", summary="TripStar 小红书搜索")
def search_xhs_notes(
    city: str = Query(..., min_length=1, max_length=80),
    keyword: str = Query("", max_length=120),
    limit: int = Query(6, ge=1, le=20),
    _user: UserInfo = Depends(_require_user),
):
    query = f"{city} {keyword}".strip()
    try:
        items = _xhs_service().search_notes(query, limit)
    except XhsCookieExpiredError as exc:
        # 外部小红书 Cookie 失效不是当前应用用户未登录；避免前端通用 401 处理跳转登录页。
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except XhsServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "enabled": True,
        "configured": True,
        "query": query,
        "items": items,
    }


@router.get("/map/geocode", summary="TripStar 高德地理编码")
def geocode_location(
    city: str = Query(..., min_length=1, max_length=80),
    keyword: str = Query(..., min_length=1, max_length=120),
    _user: UserInfo = Depends(_require_user),
):
    try:
        item = _amap_service().geocode(city, keyword)
    except AmapServiceError as exc:
        raise _map_error(exc) from exc
    return {"provider": "amap", "configured": True, "item": item}


@router.get("/map/poi", summary="TripStar 高德 POI 搜索")
def search_poi(
    city: str = Query(..., min_length=1, max_length=80),
    keyword: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(10, ge=1, le=25),
    _user: UserInfo = Depends(_require_user),
):
    try:
        items = _amap_service().search_poi(city, keyword, limit)
    except AmapServiceError as exc:
        raise _map_error(exc) from exc
    return {"provider": "amap", "configured": True, "items": items}


@router.post("/map/route", summary="TripStar 高德多点路线规划")
def plan_route(
    request: TripStarRouteRequest,
    _user: UserInfo = Depends(_require_user),
):
    try:
        route_data = _amap_service().route_many(
            [point.model_dump() for point in request.points],
            request.mode,
        )
    except AmapServiceError as exc:
        raise _map_error(exc) from exc
    return {"provider": "amap", "configured": True, "route": route_data}


@router.post("/plan", response_model=TripStarSubmitResponse, summary="提交 TripStar 旅行规划任务")
def create_plan(
    request: TripStarRequest,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(_require_user),
):
    settings = get_tripstar_settings()
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="TripStar 模块未启用")

    task_id = uuid.uuid4().hex[:8]
    request_payload = request.model_dump(mode="json")
    _store.create(task_id, request_payload, owner=user.username)
    background_tasks.add_task(_run_task, task_id, request_payload)

    return TripStarSubmitResponse(
        task_id=task_id,
        plan_id=task_id,
        status="processing",
        ws_url=f"/api/tripstar/ws/{task_id}",
        message="TripStar 旅行规划任务已提交",
    )


@router.get("/status/{task_id}", summary="查询 TripStar 任务状态")
def get_status(
    task_id: str,
    include_all: bool = Query(False, alias="all"),
    user: UserInfo = Depends(_require_user),
):
    task = _store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TripStar 任务不存在")
    if not _can_view_task(user, task, include_all=include_all):
        raise HTTPException(status_code=404, detail="TripStar 任务不存在")
    return _serialize_task(task)


@router.websocket("/ws/{task_id}")
async def websocket_status(websocket: WebSocket, task_id: str):
    await websocket.accept()
    token = websocket.cookies.get(SESSION_COOKIE_NAME, "")
    user = await run_in_threadpool(get_user_from_token, token)
    if not user:
        await websocket.close(code=1008)
        return

    include_all = str(websocket.query_params.get("all", "")).lower() in {"1", "true", "yes"}
    task = _store.get(task_id)
    if task is None:
        await websocket.send_json(
            {
                "task_id": task_id,
                "plan_id": task_id,
                "status": "failed",
                "stage": "failed",
                "progress": 100,
                "message": "TripStar 任务不存在",
                "error": "TripStar 任务不存在",
            }
        )
        await websocket.close()
        return
    if not _can_view_task(user, task, include_all=include_all):
        await websocket.close(code=1008)
        return

    settings = await run_in_threadpool(get_tripstar_settings)
    deadline = time.monotonic() + _websocket_timeout_seconds(settings)
    while time.monotonic() < deadline:
        snapshot = _serialize_task(task)
        await websocket.send_json(snapshot)
        if snapshot["status"] in {"completed", "failed"}:
            await websocket.close()
            return
        await asyncio.sleep(1)
        task = _store.get(task_id)
        if task is None:
            await websocket.send_json(
                {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "任务状态丢失",
                }
            )
            await websocket.close()
            return

    await websocket.send_json(
        {
            **_serialize_task(task),
            "stage": "ws_timeout",
            "message": "WebSocket 等待超时，任务仍在处理中，请继续轮询状态接口。",
        }
    )
    await websocket.close()


@router.get("/history", summary="查询 TripStar 历史计划")
def get_history(
    limit: int = 10,
    include_all: bool = Query(False, alias="all"),
    user: UserInfo = Depends(_require_user),
):
    if include_all and user.role != "admin":
        raise HTTPException(status_code=403, detail="权限不足")
    safe_limit = max(1, min(int(limit or 10), 50))
    owner = None if include_all else user.username
    return {"items": _store.recent_completed(safe_limit, owner=owner)}
