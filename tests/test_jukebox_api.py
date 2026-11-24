import secrets
import threading
import time
from contextlib import contextmanager

from fastapi import Request
from fastapi.testclient import TestClient

from backend.config import settings
from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.routers import jukebox
from backend.security import SlidingWindowLimiter


client = TestClient(app)


def _login(username: str = "jukebox_user", role: str = "visitor") -> None:
    token = secrets.token_urlsafe(24)
    _cache_session(token, UserInfo(username=username, role=role), time.time() + 3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)


def test_jukebox_endpoints_require_login():
    anonymous = TestClient(app)
    assert anonymous.get("/api/jukebox").status_code == 401
    assert anonymous.post("/api/jukebox", json={}).status_code == 401
    assert anonymous.post("/api/jukebox/like", json={"id": 0}).status_code == 401


def test_invalid_jukebox_inputs_return_real_status():
    _login()

    assert client.post("/api/jukebox", json={}).status_code == 400
    assert client.post("/api/jukebox/like", json={"id": 0}).status_code == 400


def test_rate_limit_is_atomic_and_bounded():
    limiter = SlidingWindowLimiter(5, 3600)
    allowed = []
    barrier = threading.Barrier(24)

    def worker(index):
        barrier.wait()
        if limiter.allow("same-ip"):
            allowed.append(index)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(allowed) == 5


def test_proxy_headers_are_ignored_unless_explicitly_enabled(monkeypatch):
    scope = {
        "type": "http",
        "headers": [
            (b"x-real-ip", b"203.0.113.9"),
            (b"x-forwarded-for", b"198.51.100.7, 10.0.0.2"),
        ],
        "client": ("10.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert jukebox._get_client_ip(request) == "10.0.0.1"

    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    assert jukebox._get_client_ip(request) == "203.0.113.9"


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self._row = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._row = None

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        return None


def test_like_rejects_missing_request_before_insert(monkeypatch):
    _login()
    cursor = _FakeCursor()
    connection = _FakeConnection(cursor)

    @contextmanager
    def fake_get_db():
        yield connection

    monkeypatch.setattr(jukebox, "get_db", fake_get_db)

    response = client.post("/api/jukebox/like", json={"id": 999})

    assert response.status_code == 404
    assert len(cursor.executed) == 1
    assert cursor.executed[0][0].startswith("SELECT id")
