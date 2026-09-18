"""管理员回忆备份导出"""
import datetime
import io
import json
import os
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.config import settings
from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _sessions, create_session
from backend.main import app
from backend.services import backup as backup_service

client = TestClient(app)
RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"


class FakeCursor:
    def __init__(self, payload, executed=None):
        self.payload = payload
        self.executed = executed if executed is not None else []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append(" ".join(str(sql).split()))
        text = self.executed[-1].lower()
        self._rows = []
        mapping = [
            ("love_cooking_menu_items", "menu_items"),
            ("love_cooking_menus", "menus"),
            ("love_cooking_records", "cooking_records"),
            (f"`{settings.timeline_table}`".lower(), "timeline"),
            (f"`{settings.mood_table}`".lower(), "moods"),
            (f"`{settings.wish_table}`".lower(), "wishes"),
            (f"`{settings.capsule_table}`".lower(), "capsules"),
            (f"`{settings.map_photos_table}`".lower(), "marker_photos"),
            (f"`{settings.map_table}`".lower(), "markers"),
            ("love_photos", "photos"),
            (f"`{settings.music_table}`".lower(), "playlist"),
        ]
        for needle, key in mapping:
            if needle in text:
                self._rows = list(self.payload.get(key, []))
                return

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, payload, executed=None):
        self.cursor_obj = FakeCursor(payload, executed)

    def cursor(self):
        return self.cursor_obj


class FakeObject:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeBucket:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, key):
        if key not in self.objects:
            raise FileNotFoundError(key)
        return FakeObject(self.objects[key])


@contextmanager
def fake_get_db(payload=None, executed=None):
    yield FakeConnection(payload or {}, executed)


def login_as(role: str) -> TestClient:
    local = TestClient(app)
    token = create_session(UserInfo(username=f"{role}_backup", role=role))
    local.cookies.set(SESSION_COOKIE_NAME, token)
    return local


def wait_status(admin: TestClient, *wanted, timeout=8.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = admin.get("/api/backup/export").json()
        if last.get("status") in wanted:
            return last
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting {wanted}: {last}")


def setup_function():
    client.cookies.clear()
    _sessions.clear()
    backup_service.reset_jobs()


def teardown_function():
    backup_service.reset_jobs()
    if RUNTIME_ROOT.exists():
        import shutil
        shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)


def isolate_paths(monkeypatch) -> Path:
    base_dir = RUNTIME_ROOT / uuid4().hex
    (base_dir / "docs" / "photos").mkdir(parents=True)
    monkeypatch.setattr(settings, "base_dir", base_dir)
    return base_dir


def sample_payload(photo_name="day-one.jpg"):
    day = datetime.date(2023, 10, 26)
    return {
        "timeline": [
            (1, day, "在一起", "第一天", "", "💕"),
        ],
        "moods": [
            (1, day, "😊", "很好", 5),
        ],
        "wishes": [
            (1, "一直走下去", 0.5, 0.5, "#ffd700", datetime.datetime(2023, 10, 26, 20, 0, 0)),
        ],
        "capsules": [
            (1, "给未来的我们", datetime.date(2026, 10, 26), 0, datetime.datetime(2023, 10, 26, 21, 0, 0)),
        ],
        "markers": [
            (8, "西湖", "散步", "", 30.2, 120.1, day, datetime.datetime(2023, 10, 26, 12, 0, 0)),
        ],
        "marker_photos": [
            (8, "https://cdn.example/map/west-lake.jpg", 0),
        ],
        "photos": [
            (3, photo_name, f"https://cdn.example/photos/{photo_name}", "封面", datetime.datetime(2023, 10, 26, 10, 0, 0)),
        ],
        "playlist": [
            (1, "小幸运", "田馥甄", "123", "netease", 0),
        ],
        "cooking_records": [
            (1, 9, "番茄炒蛋", "admin", day, 5, "开心", "", "很好吃", ""),
        ],
        "menus": [
            (2, "纪念日晚餐", day, "", "done", "admin"),
        ],
        "menu_items": [
            (2, 9, "番茄炒蛋", 0, ""),
        ],
    }


def test_oss_object_key_from_url():
    assert backup_service.oss_object_key("https://bucket.oss-cn-hangzhou.aliyuncs.com/photos/a.jpg") == "photos/a.jpg"
    assert backup_service.oss_object_key("https://cdn.example/map/west-lake.jpg?x=1") == "map/west-lake.jpg"
    assert backup_service.oss_object_key("photos/a.jpg") == "photos/a.jpg"
    assert backup_service.oss_object_key("") is None


def test_anonymous_cannot_export():
    assert client.post("/api/backup/export").status_code == 401
    assert client.get("/api/backup/export").status_code == 401
    assert client.get("/api/backup/export/download").status_code == 401


def test_visitor_cannot_export():
    visitor = login_as("visitor")
    assert visitor.post("/api/backup/export").status_code == 403
    assert visitor.get("/api/backup/export").status_code == 403
    assert visitor.get("/api/backup/export/download").status_code == 403


def test_admin_export_zip_contains_memories_and_photos(monkeypatch):
    isolate_paths(monkeypatch)
    photo_name = "day-one.jpg"
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    (settings.photos_dir / photo_name).write_bytes(b"jpeg-bytes")
    payload = sample_payload(photo_name)
    sqls = []
    monkeypatch.setattr(backup_service, "get_db", lambda: fake_get_db(payload, sqls))
    monkeypatch.setattr(
        backup_service,
        "get_oss_bucket",
        lambda: FakeBucket({"map/west-lake.jpg": b"map-bytes"}),
    )

    admin = login_as("admin")
    started = admin.post("/api/backup/export")
    assert started.status_code == 200
    assert started.json()["status"] in {"packing", "done"}

    job = wait_status(admin, "done")
    assert job["stats"]["timeline"] == 1
    assert job["stats"]["photos"] == 1
    assert job["stats"]["files_downloaded"] == 2

    download = admin.get("/api/backup/export/download")
    assert download.status_code == 200
    assert "application/zip" in download.headers["content-type"]

    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = archive.namelist()
    json_name = next(name for name in names if name.endswith("memories.json"))
    md_name = next(name for name in names if name.endswith("memories.md"))
    data = json.loads(archive.read(json_name).decode("utf-8"))
    markdown = archive.read(md_name).decode("utf-8")

    assert data["timeline"][0]["title"] == "在一起"
    assert data["capsules"][0]["content"] == "给未来的我们"
    assert data["playlist"][0]["song_name"] == "小幸运"
    assert "config" not in data
    assert "cookies" not in data
    assert "users" not in data
    keys = list(_walk_keys(data))
    assert not any("cookie" in key.lower() or "password" in key.lower() or "secret" in key.lower() for key in keys)
    assert "在一起" in markdown
    assert "西湖" in markdown
    assert any(name.endswith(f"photos/{photo_name}") for name in names)
    assert any(name.endswith("map/west-lake.jpg") for name in names)
    assert archive.read(next(name for name in names if name.endswith(photo_name))) == b"jpeg-bytes"

    joined = " ".join(sqls).lower()
    assert "love_config" not in joined
    assert "love_users" not in joined
    assert "love_page_password" not in joined
    assert "ai_messages" not in joined


def test_second_export_while_packing_returns_same_job(monkeypatch):
    isolate_paths(monkeypatch)
    monkeypatch.setattr(backup_service, "get_db", lambda: fake_get_db({}))
    monkeypatch.setattr(backup_service, "get_oss_bucket", lambda: None)
    started = threading.Event()
    release = threading.Event()

    def blocked(job_id):
        started.set()
        release.wait(5)

    monkeypatch.setattr(backup_service, "run_export_job", blocked)
    admin = login_as("admin")
    first = admin.post("/api/backup/export")
    assert started.wait(2)
    second = admin.post("/api/backup/export")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["status"] == "packing"
    release.set()


def test_download_before_ready_is_not_found(monkeypatch):
    isolate_paths(monkeypatch)
    admin = login_as("admin")
    assert admin.get("/api/backup/export").json() == {"status": "idle"}
    assert admin.get("/api/backup/export/download").status_code == 404


def _walk_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from _walk_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)
