"""某一天聚合接口"""
import datetime
import os
import sys
from contextlib import contextmanager

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.config import settings
from backend.dependencies import (
    SESSION_COOKIE_NAME,
    UserInfo,
    _sessions,
    create_session,
)
from backend.routers import day as day_router


client = TestClient(app)


class FakeCursor:
    def __init__(self, payload):
        self.payload = payload
        self.executed = []
        self._fetchall = []
        self._fetchone = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        text = " ".join(str(sql).split()).lower()
        if "distinct" in text and f"from `{settings.timeline_table}`".lower() in text:
            self._fetchall = self.payload.get("timeline_dates", [])
            self._fetchone = None
        elif "distinct" in text and f"from `{settings.mood_table}`".lower() in text:
            self._fetchall = self.payload.get("mood_dates", [])
            self._fetchone = None
        elif "distinct" in text and f"from `{settings.map_table}`".lower() in text:
            self._fetchall = self.payload.get("marker_dates", [])
            self._fetchone = None
        elif f"from `{settings.timeline_table}`".lower() in text:
            self._fetchall = self.payload.get("timeline", [])
            self._fetchone = None
        elif f"from `{settings.mood_table}`".lower() in text:
            rows = self.payload.get("mood", [])
            self._fetchall = rows
            self._fetchone = rows[0] if rows else None
        elif f"from `{settings.map_photos_table}`".lower() in text:
            self._fetchall = self.payload.get("marker_photos", [])
            self._fetchone = None
        elif f"from `{settings.map_table}`".lower() in text:
            self._fetchall = self.payload.get("markers", [])
            self._fetchone = None
        elif "from love_photos" in text:
            self._fetchall = self.payload.get("photos" if "where" in text else "photo_dates", [])
            self._fetchone = None
        else:
            self._fetchall = []
            self._fetchone = None

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, payload):
        self.cursor_obj = FakeCursor(payload)

    def cursor(self):
        return self.cursor_obj


def login_as(role: str = "visitor", gallery_unlocked: bool = False) -> str:
    token = create_session(
        UserInfo(username=f"{role}_user", role=role, gallery_unlocked=gallery_unlocked)
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token


@contextmanager
def fake_get_db(payload=None):
    yield FakeConnection(payload or {})


def setup_function():
    client.cookies.clear()
    _sessions.clear()


def test_day_requires_authentication():
    response = client.get("/api/day/2023-10-26")
    assert response.status_code == 401


def test_day_rejects_invalid_date():
    login_as()
    response = client.get("/api/day/2023-13-40")
    assert response.status_code == 400
    assert response.json()["error"] == "invalid date"


def test_day_empty_payload(monkeypatch):
    login_as()
    monkeypatch.setattr(day_router, "get_db", lambda: fake_get_db({}))
    monkeypatch.setattr(day_router, "get_oss_bucket", lambda: None)

    response = client.get("/api/day/2023-10-26")

    assert response.status_code == 200
    data = response.json()
    assert data["date"] == "2023-10-26"
    assert data["timeline"] == []
    assert data["mood"] is None
    assert data["places"] == []
    assert data["photos"] == []
    assert data["gallery_unlocked"] is False


def test_day_aggregates_existing_records(monkeypatch):
    login_as(gallery_unlocked=True)
    payload = {
        "timeline": [
            (1, datetime.date(2023, 10, 26), "第一次见面", "很开心", "https://img/a.jpg", "💕"),
        ],
        "mood": [(9, datetime.date(2023, 10, 26), "🥰", "心动", 5)],
        "markers": [
            (3, "黄鹤楼", "一起看江", "https://img/cover.jpg", 30.54, 114.30, datetime.date(2023, 10, 26)),
        ],
        "marker_photos": [(3, "https://img/p1.jpg")],
        "photos": [
            (7, "meet.jpg", "/photos/meet.jpg", "那天", datetime.datetime(2023, 10, 26, 18, 30, 0)),
        ],
    }
    monkeypatch.setattr(day_router, "get_db", lambda: fake_get_db(payload))
    monkeypatch.setattr(day_router, "get_oss_bucket", lambda: None)

    response = client.get("/api/day/2023-10-26")

    assert response.status_code == 200
    data = response.json()
    assert data["timeline"][0]["title"] == "第一次见面"
    assert data["mood"]["emoji"] == "🥰"
    assert data["places"][0]["title"] == "黄鹤楼"
    assert data["places"][0]["photos"] == ["https://img/p1.jpg"]
    assert data["photos"][0]["filename"] == "meet.jpg"
    assert data["photos"][0]["created_at"] == "2023-10-26 18:30:00"
    assert data["gallery_unlocked"] is True


def test_day_hides_photos_until_gallery_unlocked(monkeypatch):
    login_as(gallery_unlocked=False)
    conn = FakeConnection(
        {
            "photos": [
                (7, "secret.jpg", "/photos/secret.jpg", "", datetime.datetime(2023, 10, 26, 12, 0, 0)),
            ],
        }
    )

    @contextmanager
    def tracking_get_db():
        yield conn

    monkeypatch.setattr(day_router, "get_db", tracking_get_db)
    monkeypatch.setattr(day_router, "get_oss_bucket", lambda: None)

    response = client.get("/api/day/2023-10-26")

    assert response.status_code == 200
    data = response.json()
    assert data["photos"] == []
    assert data["gallery_unlocked"] is False
    sqls = [" ".join(str(sql).split()).lower() for sql, _ in conn.cursor_obj.executed]
    assert all("love_photos" not in sql for sql in sqls)


def test_random_memory_requires_authentication():
    response = client.get("/api/memory")
    assert response.status_code == 401


def test_random_memory_enabled_by_default(monkeypatch):
    login_as(gallery_unlocked=True)
    payload = {
        "timeline_dates": [(datetime.date(2023, 10, 26),)],
        "mood_dates": [],
        "marker_dates": [],
        "photo_dates": [],
        "timeline": [
            (1, datetime.date(2023, 10, 26), "第一次见面", "很开心", "https://img/a.jpg", "💕"),
        ],
        "mood": [],
        "markers": [],
        "marker_photos": [],
        "photos": [],
    }
    monkeypatch.setattr(day_router, "get_db", lambda: fake_get_db(payload))
    monkeypatch.setattr(day_router, "get_oss_bucket", lambda: None)
    monkeypatch.setattr(day_router, "get_config", lambda key: "")
    monkeypatch.setattr(day_router, "_today", lambda: datetime.date(2026, 9, 18))

    response = client.get("/api/memory")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["memory"]["date"] == "2023-10-26"
    assert data["memory"]["story_title"] == "第一次见面"
    assert data["memory"]["cover_url"] == "https://img/a.jpg"


def test_random_memory_hidden_when_admin_turns_off(monkeypatch):
    login_as("admin")
    monkeypatch.setattr(day_router, "get_config", lambda key: "off")
    queried = {"called": False}

    def boom():
        queried["called"] = True
        return fake_get_db({})

    monkeypatch.setattr(day_router, "get_db", boom)

    response = client.get("/api/memory")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "memory": None}
    assert queried["called"] is False


def test_visitor_cannot_toggle_random_memory():
    login_as("visitor")
    response = client.put("/api/memory", json={"enabled": False})
    assert response.status_code == 403


def test_admin_can_toggle_random_memory(monkeypatch):
    login_as("admin")
    saved = {}

    def fake_set(key, value):
        saved[key] = value

    monkeypatch.setattr(day_router, "set_config", fake_set)

    response = client.put("/api/memory", json={"enabled": False})

    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    assert saved[day_router.MEMORY_CONFIG_KEY] == "off"


def test_random_memory_skips_gallery_photos_until_unlocked(monkeypatch):
    login_as(gallery_unlocked=False)
    payload = {
        "timeline_dates": [],
        "mood_dates": [],
        "marker_dates": [],
        "photo_dates": [(datetime.date(2024, 1, 1),)],
        "timeline": [],
        "mood": [],
        "markers": [],
        "photos": [
            (7, "secret.jpg", "/photos/secret.jpg", "", datetime.datetime(2024, 1, 1, 12, 0, 0)),
        ],
    }
    conn = FakeConnection(payload)

    @contextmanager
    def tracking_get_db():
        yield conn

    monkeypatch.setattr(day_router, "get_db", tracking_get_db)
    monkeypatch.setattr(day_router, "get_oss_bucket", lambda: None)
    monkeypatch.setattr(day_router, "get_config", lambda key: "on")

    response = client.get("/api/memory")

    assert response.status_code == 200
    assert response.json()["memory"] is None
    sqls = [" ".join(str(sql).split()).lower() for sql, _ in conn.cursor_obj.executed]
    assert all("love_photos" not in sql for sql in sqls)
