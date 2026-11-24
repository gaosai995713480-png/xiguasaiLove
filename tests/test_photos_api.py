"""
照片接口回归测试
"""
import io
import os
import sys
import shutil
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.config import settings
from backend.dependencies import (
    SESSION_COOKIE_NAME,
    UserInfo,
    _cache_session,
    _session_expiries,
    _sessions,
    _sessions_lock,
    get_current_user,
)
from backend.routers import gallery as gallery_router
from backend.routers import photos as photos_router


client = TestClient(app)
RUNTIME_ROOT = Path(__file__).resolve().parent / "_runtime"


def login_as(role: str = "visitor") -> str:
    token = f"photos-{uuid4().hex}"
    _cache_session(
        token,
        UserInfo(username=f"{role}_user", role=role),
        time.time() + 3600,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token


class FakePhotoCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        return None

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePhotoConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakePhotoCursor(self.rows)


@contextmanager
def fake_get_db(rows=None):
    yield FakePhotoConnection(rows or [])


class UploadCursor:
    def __init__(self, existing=(), fail_insert=False):
        self.existing = set(existing)
        self.fail_insert = fail_insert
        self.inserted = []
        self.deleted = []
        self.lastrowid = 1
        self.rowcount = 1
        self._fetchall = []
        self._fetchone = None

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        if normalized.startswith("SELECT filename FROM love_photos"):
            self._fetchall = [(name,) for name in self.existing]
            return
        if normalized.startswith("INSERT INTO love_photos"):
            if self.fail_insert:
                raise RuntimeError("simulated db insert failure")
            self.inserted.append(params)
            return
        if normalized.startswith("DELETE FROM love_photos"):
            self.deleted.append(params)
            return

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class UploadConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_called = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_called = True


class FakeBucket:
    def __init__(self):
        self.deleted = []

    def delete_object(self, key):
        self.deleted.append(key)


class FakeUploader:
    def __init__(self):
        self.objects = set()
        self.calls = []

    def __call__(self, name, data, prefix="photos"):
        key = f"{prefix}/{name}"
        self.calls.append((key, data))
        if key in self.objects:
            return "exists"
        self.objects.add(key)
        return "ok"


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


@contextmanager
def existing_upload_db(connection):
    yield connection


def setup_function():
    client.cookies.clear()
    with _sessions_lock:
        _sessions.clear()
        _session_expiries.clear()


def teardown_function():
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)


def isolated_base_dir(monkeypatch) -> Path:
    base_dir = RUNTIME_ROOT / uuid4().hex
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "base_dir", base_dir)
    return base_dir


def isolate_photo_runtime(monkeypatch) -> Path:
    base_dir = isolated_base_dir(monkeypatch)

    def fake_set_gallery_unlocked(request, unlocked=True):
        user = get_current_user(request)
        if user:
            user.gallery_unlocked = bool(unlocked)

    monkeypatch.setattr(photos_router, "get_db", lambda: fake_get_db([]))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: None)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "")
    monkeypatch.setattr(gallery_router, "set_gallery_unlocked", fake_set_gallery_unlocked)
    return base_dir


def test_photos_json_requires_authentication():
    response = client.get("/photos.json")

    assert response.status_code == 401


def test_photos_json_requires_gallery_unlock(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    photos_dir = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)
    (photos_dir / "sample.jpg").write_bytes(b"fake-image")
    monkeypatch.setattr(gallery_router, "verify_page_password", lambda page_key, password: password == "secret")

    login_as("visitor")

    locked_response = client.get("/photos.json")
    verify_response = client.post("/api/gallery/verify", json={"password": "secret"})
    unlocked_response = client.get("/photos.json")

    assert locked_response.status_code == 403
    assert verify_response.status_code == 200
    assert verify_response.json() == {"ok": True}
    assert unlocked_response.status_code == 200
    assert unlocked_response.json() == [
        {
            "id": 0,
            "filename": "sample.jpg",
            "url": "photos/sample.jpg",
            "description": "",
            "created_at": "",
        }
    ]


def test_photo_file_requires_gallery_unlock(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    photos_dir = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)
    (photos_dir / "sample.jpg").write_bytes(b"fake-image")
    login_as("visitor")

    response = client.get("/photos/sample.jpg")

    assert response.status_code == 403


def test_upload_invalid_extension_returns_400(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "notes.txt"},
        content=b"hello",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid file name"


def test_import_invalid_zip_returns_400(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    login_as("admin")

    response = client.post("/photos/import", content=b"not-a-zip")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid zip file"


def test_verify_gallery_unlock_grants_access(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    photos_dir = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)
    (photos_dir / "sample.jpg").write_bytes(b"fake-image")
    monkeypatch.setattr(gallery_router, "verify_page_password", lambda page_key, password: password == "secret")

    login_as("visitor")

    verify_response = client.post("/api/gallery/verify", json={"password": "secret"})
    list_response = client.get("/photos.json")

    assert verify_response.status_code == 200
    assert verify_response.json() == {"ok": True}
    assert list_response.status_code == 200
    assert list_response.json() == [
        {
            "id": 0,
            "filename": "sample.jpg",
            "url": "photos/sample.jpg",
            "description": "",
            "created_at": "",
        }
    ]


def test_direct_upload_with_existing_name_gets_unique_name(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor(existing={"sample.jpg"})
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "sample.jpg"},
        content=b"new-image",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "sample_2.jpg"
    assert response.json()["renamed"] is True
    assert [call[0] for call in uploader.calls] == ["photos/sample_2.jpg"]
    assert cursor.inserted[0][0] == "sample_2.jpg"
    assert connection.commit_called is True


def test_direct_upload_does_not_overwrite_existing_oss_object(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor()
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    uploader.objects.add("photos/sample.jpg")
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "sample.jpg"},
        content=b"new-image",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "sample_2.jpg"
    assert "photos/sample.jpg" in uploader.objects
    assert "photos/sample_2.jpg" in uploader.objects


def test_direct_upload_db_failure_cleans_only_new_object(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor(fail_insert=True)
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "new.jpg"},
        content=b"new-image",
    )

    assert response.status_code == 500
    assert bucket.deleted == ["photos/new.jpg"]
    assert connection.commit_called is False


def test_db_failure_does_not_delete_prior_same_name_oss_object(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor(fail_insert=True)
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    uploader.objects.add("photos/sample.jpg")
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "sample.jpg"},
        content=b"new-image",
    )

    assert response.status_code == 500
    assert bucket.deleted == ["photos/sample_2.jpg"]
    assert "photos/sample.jpg" in uploader.objects


def test_zip_same_basename_is_renamed_not_overwritten(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor()
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/import",
        content=zip_bytes(
            [
                ("tripA/cover.jpg", b"first"),
                ("tripB/cover.jpg", b"second"),
            ]
        ),
    )

    assert response.status_code == 200
    assert response.json()["saved"] == 2
    assert response.json()["names"] == ["cover.jpg", "cover_2.jpg"]
    assert [call[0] for call in uploader.calls] == [
        "photos/cover.jpg",
        "photos/cover_2.jpg",
    ]
    assert connection.commit_called is True


def test_zip_db_failure_cleans_uploaded_objects(monkeypatch):
    isolated_base_dir(monkeypatch)
    cursor = UploadCursor(fail_insert=True)
    connection = UploadConnection(cursor)
    bucket = FakeBucket()
    uploader = FakeUploader()
    monkeypatch.setattr(photos_router, "get_db", lambda: existing_upload_db(connection))
    monkeypatch.setattr(photos_router, "get_oss_bucket", lambda: bucket)
    monkeypatch.setattr(photos_router, "get_oss_domain", lambda: "https://cdn.example")
    monkeypatch.setattr(photos_router, "upload_to_oss_exclusive", uploader)
    login_as("admin")

    response = client.post(
        "/photos/import",
        content=zip_bytes([("cover.jpg", b"image")]),
    )

    assert response.status_code == 500
    assert bucket.deleted == ["photos/cover.jpg"]


def test_zip_entry_limit_returns_413(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    monkeypatch.setattr(photos_router, "MAX_ZIP_ENTRIES", 1)
    login_as("admin")

    response = client.post(
        "/photos/import",
        content=zip_bytes(
            [
                ("one.jpg", b"one"),
                ("two.jpg", b"two"),
            ]
        ),
    )

    assert response.status_code == 413


def test_zip_single_file_limit_returns_413(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    monkeypatch.setattr(photos_router, "MAX_ZIP_SINGLE_FILE_BYTES", 3)
    login_as("admin")

    response = client.post(
        "/photos/import",
        content=zip_bytes([("large.jpg", b"four")]),
    )

    assert response.status_code == 413


def test_local_upload_with_same_name_keeps_both_files(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    photos_dir = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)
    original = photos_dir / "sample.jpg"
    original.write_bytes(b"original")
    login_as("admin")

    response = client.post(
        "/photos/upload-file",
        headers={"X-File-Name": "sample.jpg"},
        content=b"replacement",
    )

    assert response.status_code == 200
    assert response.json()["name"] == "sample_2.jpg"
    assert original.read_bytes() == b"original"
    assert (photos_dir / "sample_2.jpg").read_bytes() == b"replacement"


def test_delete_photo_rejects_non_image_name(monkeypatch):
    isolate_photo_runtime(monkeypatch)
    login_as("admin")

    response = client.delete("/photos/notes.txt")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid photo name"}
