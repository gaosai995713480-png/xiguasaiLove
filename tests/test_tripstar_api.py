import time
import logging
import secrets

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.tripstar import router as tripstar_router
from backend.tripstar.config import TripStarSettings
from backend.tripstar.task_store import TripStarTaskStore


client = TestClient(app)


def _login(username: str = "tripstar_user", role: str = "visitor") -> None:
    token = secrets.token_urlsafe(24)
    _cache_session(token, UserInfo(username=username, role=role), time.time() + 3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)


@pytest.fixture(autouse=True)
def isolated_tripstar(monkeypatch, tmp_path):
    settings = TripStarSettings(
        enabled=True,
        mock_mode=True,
        llm_model_id="",
        llm_api_key="",
        llm_base_url="",
        llm_timeout=600,
        amap_web_key="",
        xhs_cookie="",
        enable_xhs=False,
        google_maps_api_key="",
        google_maps_proxy="",
        amap_web_js_key="",
        amap_security_js_code="",
    )
    store = TripStarTaskStore(tmp_path, stale_after_seconds=60)
    monkeypatch.setattr(tripstar_router, "get_tripstar_settings", lambda: settings)
    monkeypatch.setattr(tripstar_router, "_store", store)
    client.cookies.clear()
    _login()
    yield store
    client.cookies.clear()


def test_tripstar_suppresses_httpx_info_logs_to_avoid_key_leakage():
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_tripstar_health_reports_mock_mode_without_llm_token():
    response = client.get("/api/tripstar/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "tripstar"
    assert payload["status"] == "healthy"
    assert payload["mock_mode"] is True
    assert payload["task_store"] == "ready"


def test_tripstar_plan_reaches_terminal_state_in_mock_mode():
    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "travel_days": 3,
            "preferences": ["历史文化", "本地美食"],
            "language": "zh",
        },
    )

    assert response.status_code == 200
    submitted = response.json()
    assert submitted["status"] == "processing"
    assert submitted["task_id"]

    task_id = submitted["task_id"]
    latest = None
    for _ in range(20):
        status_response = client.get(f"/api/tripstar/status/{task_id}")
        assert status_response.status_code == 200
        latest = status_response.json()
        if latest["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)

    assert latest is not None
    assert latest["status"] == "completed"
    assert latest["progress"] == 100
    assert latest["result"]["success"] is True
    assert latest["result"]["data"]["city"] == "西安"
    assert latest["result"]["data"]["travel_days"] == 3
    assert latest["result"]["data"]["days"], "应生成至少一天行程，避免前端空转"
    first_attraction = latest["result"]["data"]["days"][0]["attractions"][0]
    assert first_attraction["location"]["longitude"]
    assert first_attraction["location"]["latitude"]
    assert latest["result"]["data"]["map_routes"], "应生成地图路线数据，避免前端地图空白"


def test_tripstar_mock_plan_uses_detailed_city_pois_for_wuhan():
    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "武汉",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "travel_days": 3,
            "preferences": ["历史文化", "本地美食"],
            "language": "zh",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    latest = client.get(f"/api/tripstar/status/{task_id}").json()
    plan = latest["result"]["data"]
    attraction_names = [
        attraction["name"]
        for day in plan["days"]
        for attraction in day["attractions"]
    ]

    assert "黄鹤楼" in attraction_names
    assert "湖北省博物馆" in attraction_names
    assert all("城市地标" not in name for name in attraction_names)
    assert all(
        attraction.get("location", {}).get("longitude")
        for day in plan["days"]
        for attraction in day["attractions"]
    )
    assert plan["map_routes"][0]["source"] == "preset"


def test_tripstar_mock_plan_does_not_repeat_same_route_for_long_wuhan_trip():
    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "武汉",
            "start_date": "2026-06-01",
            "end_date": "2026-06-20",
            "travel_days": 20,
            "preferences": ["历史文化", "本地美食"],
            "language": "zh",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    latest = client.get(f"/api/tripstar/status/{task_id}").json()
    plan = latest["result"]["data"]
    route_names = [
        " -> ".join(point["name"] for point in route["points"])
        for route in plan["map_routes"]
    ]

    assert len(route_names) == 20
    assert len(set(route_names)) == 20
    assert route_names[4] != "黄鹤楼 -> 户部巷"
    assert all("城市地标" not in route for route in route_names)


def test_tripstar_real_planner_error_marks_task_failed(monkeypatch):
    from backend.tripstar import planner as tripstar_planner

    class BrokenPlanner:
        def __init__(self, settings):
            self.settings = settings

        def plan(self, request, progress):
            progress("llm", "调用失败", 50)
            raise RuntimeError("planner unavailable")

    monkeypatch.setattr(tripstar_planner, "RealTripStarPlanner", BrokenPlanner)
    monkeypatch.setattr(
        tripstar_router,
        "get_tripstar_settings",
        lambda: TripStarSettings(
            enabled=True,
            mock_mode=False,
            llm_model_id="demo-model",
            llm_api_key="demo-key",
            llm_base_url="https://example.invalid/v1",
            llm_timeout=1,
            amap_web_key="",
            xhs_cookie="",
            enable_xhs=False,
        ),
    )

    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "travel_days": 2,
            "preferences": ["历史文化"],
            "language": "zh",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    latest = client.get(f"/api/tripstar/status/{task_id}").json()

    assert latest["status"] == "failed"
    assert latest["error"] == "planner unavailable"


def test_tripstar_plan_uses_real_planner_when_llm_configured(monkeypatch):
    from backend.tripstar import planner as tripstar_planner
    from backend.tripstar import router as tripstar_router
    from backend.tripstar.config import TripStarSettings

    class FakeRealTripStarPlanner:
        def __init__(self, settings):
            self.settings = settings

        def plan(self, request, progress):
            progress("llm", "正在使用真实 LLM planner...", 50)
            return {
                "success": True,
                "message": "真实 LLM 旅行计划生成成功",
                "data": {
                    "city": request.city,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                    "travel_days": request.travel_days,
                    "language": request.language,
                    "preferences": request.preferences,
                    "overview": "LLM 生成的攻略",
                    "days": [
                        {
                            "day": 1,
                            "title": "LLM Day 1",
                            "summary": "真实 planner 输出",
                            "attractions": [],
                            "meals": [],
                            "transportation": "",
                            "hotel_suggestion": "",
                        }
                    ],
                    "map_routes": [],
                },
                "graph_data": {"nodes": [], "edges": [], "categories": []},
                "mock_mode": False,
                "real_planner_ready": True,
            }

    monkeypatch.setattr(tripstar_planner, "RealTripStarPlanner", FakeRealTripStarPlanner)
    monkeypatch.setattr(
        tripstar_router,
        "get_tripstar_settings",
        lambda: TripStarSettings(
            enabled=True,
            mock_mode=False,
            llm_model_id="demo-model",
            llm_api_key="demo-key",
            llm_base_url="https://example.invalid/v1",
            llm_timeout=1,
            amap_web_key="",
            xhs_cookie="",
            enable_xhs=False,
        ),
    )

    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "武汉",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "travel_days": 1,
            "preferences": ["历史文化"],
            "language": "zh",
        },
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    latest = client.get(f"/api/tripstar/status/{task_id}").json()

    assert latest["status"] == "completed"
    assert latest["result"]["mock_mode"] is False
    assert latest["result"]["real_planner_ready"] is True
    assert latest["result"]["message"] == "真实 LLM 旅行计划生成成功"


def test_tripstar_status_unknown_task_is_404_not_processing_loop():
    response = client.get("/api/tripstar/status/not-exists")

    assert response.status_code == 404
    assert response.json()["detail"] == "TripStar 任务不存在"


def test_tripstar_ws_unknown_task_sends_terminal_failed_snapshot():
    with client.websocket_connect("/api/tripstar/ws/not-exists") as websocket:
        payload = websocket.receive_json()

    assert payload["task_id"] == "not-exists"
    assert payload["status"] == "failed"
    assert payload["progress"] == 100
    assert payload["error"] == "TripStar 任务不存在"


def test_tripstar_non_health_endpoints_require_login():
    client.cookies.clear()

    assert client.post("/api/tripstar/plan", json={}).status_code == 401
    assert client.get("/api/tripstar/status/not-exists").status_code == 401
    assert client.get("/api/tripstar/history").status_code == 401
    assert client.get("/api/tripstar/map/config").status_code == 401
    assert client.get("/api/tripstar/xhs/status").status_code == 401


def test_tripstar_websocket_requires_login():
    anonymous = TestClient(app)

    with anonymous.websocket_connect("/api/tripstar/ws/owned001") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 1008


def test_tripstar_plan_records_owner(isolated_tripstar):
    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "travel_days": 1,
        },
    )

    assert response.status_code == 200
    task = isolated_tripstar.get(response.json()["task_id"])
    assert task["owner"] == "tripstar_user"


def test_tripstar_task_visibility_is_owner_scoped_and_admin_can_view_all(isolated_tripstar):
    isolated_tripstar.create(
        "owned001",
        {"city": "西安", "start_date": "2026-06-01", "end_date": "2026-06-01", "travel_days": 1},
        owner="alice",
    )
    isolated_tripstar.update(
        "owned001",
        status="completed",
        result={"data": {"city": "西安", "start_date": "2026-06-01", "end_date": "2026-06-01", "travel_days": 1}},
    )

    _login("bob")
    assert client.get("/api/tripstar/status/owned001").status_code == 404
    assert client.get("/api/tripstar/history").json()["items"] == []
    assert client.get("/api/tripstar/history?all=true").status_code == 403

    _login("admin_user", role="admin")
    assert client.get("/api/tripstar/status/owned001?all=true").status_code == 200
    admin_history = client.get("/api/tripstar/history?all=true").json()["items"]
    assert admin_history[0]["task_id"] == "owned001"


def test_tripstar_preferences_are_bounded():
    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "travel_days": 1,
            "preferences": ["x"] * 11,
        },
    )

    assert response.status_code == 422

    response = client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "travel_days": 1,
            "preferences": ["x" * 51],
        },
    )
    assert response.status_code == 422


def test_tripstar_websocket_timeout_tracks_llm_timeout():
    class Settings:
        llm_timeout = 600

    assert tripstar_router._websocket_timeout_seconds(Settings()) == 1320.0
