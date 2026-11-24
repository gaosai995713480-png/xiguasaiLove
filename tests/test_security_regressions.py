"""Root 鉴权、会话、限流与安全初始化回归测试。"""
import datetime
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import database, dependencies
from backend.config import settings
from backend.main import app
from backend.routers import auth as auth_router
from backend.routers import danmu as danmu_router
from backend.security import login_ip_limiter, login_limiter


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cached_sessions():
    client.cookies.clear()
    with dependencies._sessions_lock:
        dependencies._sessions.clear()
        dependencies._session_expiries.clear()
    yield
    client.cookies.clear()
    with dependencies._sessions_lock:
        dependencies._sessions.clear()
        dependencies._session_expiries.clear()


def cache_user(username: str, role: str = "visitor", *, persisted: bool = False) -> str:
    token = f"security-{uuid4().hex}"
    dependencies._cache_session(
        token,
        dependencies.UserInfo(username=username, role=role),
        time.time() + 3600,
        persisted=persisted,
    )
    return token


def test_spa_fallback_blocks_path_traversal(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (docs_dir / "favicon.svg").write_text("<svg>inside</svg>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(settings, "base_dir", tmp_path)

    traversal_paths = (
        "/%2e%2e%2Fsecret.txt",
        "/..%2Fsecret.txt",
        "/%2e%2e%5Csecret.txt",
    )
    for path in traversal_paths:
        response = client.get(path)
        assert response.status_code == 404, path
        assert "secret" not in response.text

    inside = client.get("/favicon.svg")
    assert inside.status_code == 200
    assert "inside" in inside.text


def test_spa_fallback_cannot_read_private_gallery_files(tmp_path, monkeypatch):
    photos_dir = tmp_path / "docs" / "photos"
    photos_dir.mkdir(parents=True)
    (photos_dir / "private.jpg").write_bytes(b"private-image")
    (tmp_path / "docs" / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    monkeypatch.setattr(settings, "base_dir", tmp_path)

    response = client.get("/%2e%2e%2Fdocs%2Fphotos%2Fprivate.jpg")

    assert response.status_code == 404
    assert response.content != b"private-image"


@pytest.mark.parametrize(
    "path",
    [
        "/api/definitely-not-real",
        "/auth/definitely-not-real",
        "/missing.jpg",
    ],
)
def test_unknown_api_and_missing_static_return_404(path):
    response = client.get(path)

    assert response.status_code == 404
    assert "text/html" not in response.headers.get("content-type", "")


class SessionCursor:
    def __init__(self, row):
        self.row = row
        self.executed = []
        self._fetchone = None

    def execute(self, sql, params=None):
        self.executed.append((" ".join(str(sql).split()), params))
        if f"FROM `{settings.sessions_table}`" in str(sql):
            self._fetchone = self.row

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class SessionConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_called = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_called = True


@contextmanager
def session_db(cursor):
    yield SessionConnection(cursor)


def persist_session_read(monkeypatch, row):
    cursor = SessionCursor(row)
    monkeypatch.setattr(dependencies, "ensure_session_table", lambda: None)
    monkeypatch.setattr(dependencies, "get_db", lambda: session_db(cursor))
    return cursor


def test_valid_session_can_be_restored_from_database(monkeypatch):
    expiry = datetime.datetime.now() + datetime.timedelta(minutes=5)
    cursor = persist_session_read(
        monkeypatch,
        ("restored-user", "visitor", 1, expiry, 0),
    )

    user = dependencies.get_user_from_token("persisted-token")

    assert user is not None
    assert user.username == "restored-user"
    assert user.gallery_unlocked is True
    assert not any("DELETE FROM" in sql for sql, _ in cursor.executed)


def test_expired_server_session_is_rejected_and_deleted(monkeypatch):
    expiry = datetime.datetime.now() - datetime.timedelta(seconds=1)
    cursor = persist_session_read(
        monkeypatch,
        ("expired-user", "visitor", 0, expiry, 0),
    )

    assert dependencies.get_user_from_token("expired-token") is None
    assert any("DELETE FROM" in sql for sql, _ in cursor.executed)


def test_disabled_user_session_is_rejected_and_deleted(monkeypatch):
    expiry = datetime.datetime.now() + datetime.timedelta(minutes=5)
    cursor = persist_session_read(
        monkeypatch,
        ("disabled-user", "visitor", 0, expiry, 1),
    )

    assert dependencies.get_user_from_token("disabled-token") is None
    assert any("DELETE FROM" in sql for sql, _ in cursor.executed)


def test_revoke_user_sessions_clears_local_cache_and_database(monkeypatch):
    token = cache_user("revoked-user")
    cursor = SessionCursor(None)
    monkeypatch.setattr(dependencies, "ensure_session_table", lambda: None)
    monkeypatch.setattr(dependencies, "get_db", lambda: session_db(cursor))

    dependencies.revoke_user_sessions("revoked-user")

    assert token not in dependencies._sessions
    assert token not in dependencies._session_expiries
    assert any(
        "DELETE FROM" in sql and params == ("revoked-user",)
        for sql, params in cursor.executed
    )


def test_cached_session_revalidates_external_revocation(monkeypatch):
    token = cache_user("cross-worker-user", persisted=True)
    persist_session_read(monkeypatch, None)

    assert dependencies.get_user_from_token(token) is None


class NoUserCursor:
    def execute(self, sql, params=None):
        return None

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class NoUserConnection:
    def cursor(self):
        return NoUserCursor()


@contextmanager
def no_user_db():
    yield NoUserConnection()


def test_login_rate_limit_blocks_repeated_failures(monkeypatch):
    client_ip = "198.51.100.10"
    username = "security-rate-user"
    user_key = f"login:{client_ip}:{username}"
    ip_key = f"login-ip:{client_ip}"
    monkeypatch.setattr(auth_router, "get_client_ip", lambda request: client_ip)
    monkeypatch.setattr(auth_router, "get_db", lambda: no_user_db())
    login_limiter.reset(user_key)
    login_ip_limiter.reset(ip_key)

    try:
        responses = [
            client.post(
                "/auth/login",
                json={"username": username, "password": f"bad-{index}"},
                headers={"X-Real-IP": f"203.0.113.{index}"},
            )
            for index in range(8)
        ]
        blocked = client.post(
            "/auth/login",
            json={"username": username, "password": "still-bad"},
            headers={"X-Real-IP": "203.0.113.200"},
        )

        assert all(response.status_code == 401 for response in responses)
        assert blocked.status_code == 429
    finally:
        login_limiter.reset(user_key)
        login_ip_limiter.reset(ip_key)


def test_login_rate_limit_normalizes_case_insensitive_username(monkeypatch):
    client_ip = "198.51.100.11"
    username = "security-case-user"
    user_key = f"login:{client_ip}:{username}"
    ip_key = f"login-ip:{client_ip}"
    monkeypatch.setattr(auth_router, "get_client_ip", lambda request: client_ip)
    monkeypatch.setattr(auth_router, "get_db", lambda: no_user_db())
    login_limiter.reset(user_key)
    login_ip_limiter.reset(ip_key)

    try:
        for index in range(8):
            response = client.post(
                "/auth/login",
                json={"username": username, "password": f"bad-{index}"},
            )
            assert response.status_code == 401

        case_variant = client.post(
            "/auth/login",
            json={"username": username.title(), "password": "still-bad"},
        )
        assert case_variant.status_code == 429
    finally:
        login_limiter.reset(user_key)
        login_limiter.reset(f"login:{client_ip}:{username.title()}")
        login_ip_limiter.reset(ip_key)


class CaseSensitiveLoginCursor:
    def __init__(self):
        self._fetchone = None

    def execute(self, sql, params=None):
        if "FROM `love_users`" in str(sql) and "WHERE username" in str(sql):
            self._fetchone = (1, "visitor", 0, "PassWord")

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CaseSensitiveLoginConnection:
    def __init__(self):
        self.cursor_obj = CaseSensitiveLoginCursor()

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass


@contextmanager
def case_sensitive_login_db():
    yield CaseSensitiveLoginConnection()


def test_login_password_comparison_is_case_sensitive(monkeypatch):
    client_ip = "198.51.100.12"
    username = "case-user"
    user_key = f"login:{client_ip}:{username}"
    ip_key = f"login-ip:{client_ip}"
    monkeypatch.setattr(auth_router, "get_client_ip", lambda request: client_ip)
    monkeypatch.setattr(auth_router, "get_db", case_sensitive_login_db)
    login_limiter.reset(user_key)
    login_ip_limiter.reset(ip_key)

    try:
        response = client.post(
            "/auth/login",
            json={"username": username, "password": "password"},
        )
        assert response.status_code == 401
    finally:
        login_limiter.reset(user_key)
        login_ip_limiter.reset(ip_key)


class InitCursor:
    def __init__(self):
        self.executed = []
        self._fetchone = None

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT COUNT(*) FROM"):
            self._fetchone = (0,)
        else:
            self._fetchone = None

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class InitConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def close(self):
        pass


def test_fresh_database_initial_credentials_are_generated(monkeypatch, tmp_path):
    cursor = InitCursor()
    monkeypatch.setattr(database, "ensure_database", lambda: None)
    monkeypatch.setattr(database, "_get_connection", lambda: InitConnection(cursor))
    monkeypatch.setattr(database, "_has_column", lambda conn, table, column: True)
    monkeypatch.setattr(database, "_migrate_env_cookies", lambda conn: None)
    monkeypatch.setattr(database, "_TABLE_INIT_DONE", False)
    monkeypatch.setattr(database, "_SESSION_TABLE_READY", False)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "initial_admin_username", "")
    monkeypatch.setattr(settings, "initial_admin_password", "")
    monkeypatch.setattr(settings, "initial_gallery_password", "")
    monkeypatch.setattr(settings, "initial_invite_code", "")

    database.init_tables()

    inserts = [
        (sql, params)
        for sql, params in cursor.executed
        if sql.startswith("INSERT INTO")
    ]
    admin_insert = next(
        params for sql, params in inserts if "INTO `love_users`" in sql
    )
    gallery_insert = next(
        params for sql, params in inserts if "INTO `love_page_password`" in sql
    )
    invite_insert = next(
        params
        for sql, params in inserts
        if sql.startswith("INSERT INTO love_config") and params[0] == "INVITE_CODE"
    )

    assert admin_insert[0] == "admin"
    assert admin_insert[1] != database._LEGACY_DEFAULT_ADMIN_PASSWORD
    assert gallery_insert[0] == "gallery"
    assert gallery_insert[1] != database._LEGACY_DEFAULT_GALLERY_PASSWORD
    assert invite_insert[0] == "INVITE_CODE"
    assert invite_insert[1] != database._LEGACY_DEFAULT_INVITE_CODE


class LikeCursor:
    def __init__(self):
        self.seen = set()
        self.likes = 0
        self.rowcount = 0
        self.executed = []
        self._fetchone = None

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if normalized.startswith(f"SELECT id FROM `{settings.danmu_table}`"):
            self._fetchone = (7,)
            return
        if "INSERT IGNORE INTO" in normalized:
            key = tuple(params)
            self.rowcount = 0 if key in self.seen else 1
            self.seen.add(key)
            return
        if normalized.startswith(f"UPDATE `{settings.danmu_table}` SET likes"):
            self.likes += 1
            return
        if normalized.startswith(f"SELECT likes FROM `{settings.danmu_table}`"):
            self._fetchone = (self.likes,)

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class LikeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass


@contextmanager
def like_db(cursor):
    yield LikeConnection(cursor)


def test_danmu_like_ignores_forged_proxy_headers(monkeypatch):
    token = cache_user("danmu-user")
    cursor = LikeCursor()
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.setattr(danmu_router, "get_db", lambda: like_db(cursor))
    client.cookies.set(dependencies.SESSION_COOKIE_NAME, token)

    first = client.post(
        "/danmu/like",
        json={"id": 7},
        headers={
            "X-Real-IP": "198.51.100.21",
            "X-Forwarded-For": "198.51.100.22",
        },
    )
    second = client.post(
        "/danmu/like",
        json={"id": 7},
        headers={
            "X-Real-IP": "198.51.100.23",
            "X-Forwarded-For": "198.51.100.24",
        },
    )

    assert first.status_code == 200
    assert first.json()["liked"] is True
    assert second.status_code == 200
    assert second.json()["liked"] is False
    inserted_ips = [
        params[1]
        for sql, params in cursor.executed
        if "INSERT IGNORE INTO" in sql
    ]
    assert inserted_ips == ["testclient", "testclient"]
