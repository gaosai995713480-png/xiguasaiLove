"""私密内容接口的鉴权、状态码与输入校验回归测试。"""
import datetime
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.dependencies import (
    SESSION_COOKIE_NAME,
    UserInfo,
    _cache_session,
    _session_expiries,
    _sessions,
    _sessions_lock,
)
from backend.main import app
from backend.routers import capsule as capsule_router
from backend.routers import timeline as timeline_router


client = TestClient(app)


def login_as(role: str = "visitor") -> str:
    token = f"content-{uuid4().hex}"
    _cache_session(
        token,
        UserInfo(username=f"{role}_content", role=role),
        time.time() + 3600,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token


def setup_function():
    client.cookies.clear()
    with _sessions_lock:
        _sessions.clear()
        _session_expiries.clear()


@pytest.mark.parametrize(
    "path",
    [
        "/api/timeline",
        "/api/mood",
        "/api/wishes",
        "/api/capsules",
        "/api/map",
        "/danmu",
        "/photos.json",
        "/api/day/2026-01-01",
        "/api/recipes",
        "/api/music",
        "/api/jukebox",
        "/api/weather",
        "/api/weather/district",
        "/api/weather/locate",
        "/api/express/query?num=1&com=shunfeng",
        "/api/express/detect?num=1",
        "/api/express/companies",
        "/api/ai/status",
        "/api/tripstar/history",
        "/api/tripstar/map/config",
        "/api/tripstar/xhs/status",
    ],
)
def test_private_content_lists_require_authentication(path):
    assert client.get(path).status_code == 401


def test_tripstar_plan_requires_authentication():
    assert client.post(
        "/api/tripstar/plan",
        json={
            "city": "西安",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "travel_days": 2,
        },
    ).status_code == 401


def test_visitor_still_cannot_use_admin_only_content_writes():
    login_as("visitor")

    assert client.post(
        "/api/timeline",
        json={"event_date": "2026-01-01", "title": "x"},
    ).status_code == 403
    assert client.post(
        "/api/mood",
        json={"mood_date": "2026-01-01", "level": 3},
    ).status_code == 403
    assert client.post(
        "/api/capsules",
        json={"content": "x", "open_date": "2026-01-01"},
    ).status_code == 403


def test_wish_validation_returns_real_400():
    login_as("visitor")

    empty = client.post("/api/wishes", json={"content": ""})
    bad_coordinates = client.post(
        "/api/wishes",
        json={"content": "x", "x": "not-a-number", "y": 0.5},
    )
    out_of_range = client.post(
        "/api/wishes",
        json={"content": "x", "x": 1.1, "y": 0.5},
    )

    assert empty.status_code == 400
    assert empty.json() == {"error": "content required"}
    assert bad_coordinates.status_code == 400
    assert out_of_range.status_code == 400


def test_timeline_validation_returns_real_400():
    login_as("admin")

    empty = client.post("/api/timeline", json={"event_date": "", "title": ""})
    bad_date = client.post(
        "/api/timeline",
        json={"event_date": "2026-13-40", "title": "x"},
    )
    long_title = client.post(
        "/api/timeline",
        json={"event_date": "2026-01-01", "title": "x" * 101},
    )

    assert empty.status_code == 400
    assert bad_date.status_code == 400
    assert long_title.status_code == 400


def test_mood_validation_returns_real_400():
    login_as("admin")

    bad_date = client.post(
        "/api/mood",
        json={"mood_date": "not-a-date", "note": "", "level": 3},
    )
    long_note = client.post(
        "/api/mood",
        json={"mood_date": "2026-01-01", "note": "x" * 201, "level": 3},
    )
    bad_level = client.post(
        "/api/mood",
        json={"mood_date": "2026-01-01", "note": "", "level": "bad"},
    )

    assert bad_date.status_code == 400
    assert long_note.status_code == 400
    assert bad_level.status_code == 400


def test_capsule_and_danmu_validation_returns_real_status():
    login_as("admin")
    capsule_empty = client.post(
        "/api/capsules",
        json={"content": "", "open_date": ""},
    )
    capsule_bad_id = client.post("/api/capsules/open", json={"id": 0})
    login_as("visitor")
    danmu_empty = client.post("/danmu", json={"text": ""})

    assert capsule_empty.status_code == 400
    assert capsule_bad_id.status_code == 400
    assert danmu_empty.status_code == 400


class EmptyCursor:
    rowcount = 0

    def execute(self, sql, params=None):
        return None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class EmptyConnection:
    def cursor(self):
        return EmptyCursor()

    def commit(self):
        pass


@contextmanager
def empty_db():
    yield EmptyConnection()


def test_not_found_errors_use_404(monkeypatch):
    login_as("admin")
    monkeypatch.setattr(timeline_router, "get_db", lambda: empty_db())
    monkeypatch.setattr(capsule_router, "get_db", lambda: empty_db())

    timeline_delete = client.delete("/api/timeline?id=99")
    capsule_open = client.post("/api/capsules/open", json={"id": 99})

    assert timeline_delete.status_code == 404
    assert capsule_open.status_code == 404


class FutureCapsuleCursor(EmptyCursor):
    def fetchone(self):
        return (1, "future", datetime.date.today() + datetime.timedelta(days=1), 0)


class FutureCapsuleConnection(EmptyConnection):
    def cursor(self):
        return FutureCapsuleCursor()


@contextmanager
def future_capsule_db():
    yield FutureCapsuleConnection()


def test_future_capsule_returns_real_403(monkeypatch):
    login_as("visitor")
    monkeypatch.setattr(capsule_router, "get_db", lambda: future_capsule_db())

    response = client.post("/api/capsules/open", json={"id": 1})

    assert response.status_code == 403
    assert response.json()["can_open"] is False
