"""密码管理接口与画廊会话撤销回归测试。"""
import time
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import dependencies
from backend.config import settings
from backend.main import app
from backend.routers import gallery as gallery_router
from backend.routers import users as users_router
from backend.security import gallery_limiter, password_limiter


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_password_management_state():
    def clear():
        client.cookies.clear()
        with dependencies._sessions_lock:
            dependencies._sessions.clear()
            dependencies._session_expiries.clear()
            dependencies._persisted_tokens.clear()
        gallery_limiter.reset("gallery:testclient")
        password_limiter.reset("password:testclient:owner-user")

    clear()
    yield
    clear()


def cache_user(
    username: str,
    role: str = "visitor",
    *,
    gallery_unlocked: bool = False,
) -> str:
    token = f"password-management-{uuid4().hex}"
    dependencies._cache_session(
        token,
        dependencies.UserInfo(
            username=username,
            role=role,
            gallery_unlocked=gallery_unlocked,
        ),
        time.time() + 3600,
    )
    return token


class PasswordCursor:
    def __init__(
        self,
        *,
        target_username: str | None = "target-user",
        stored_password: str = "old-password",
    ):
        self.target_username = target_username
        self.stored_password = stored_password
        self.executed = []
        self._fetchone = None

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split())
        self.executed.append((normalized, params))
        if normalized.startswith(
            f"SELECT username FROM `{settings.users_table}` WHERE id"
        ):
            self._fetchone = (
                (self.target_username,) if self.target_username is not None else None
            )
        elif normalized.startswith(
            f"SELECT password FROM `{settings.users_table}` WHERE username"
        ):
            self._fetchone = (self.stored_password,)
        else:
            self._fetchone = None

    def fetchone(self):
        return self._fetchone

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class PasswordConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_count = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_count += 1


@contextmanager
def password_db(cursor):
    yield PasswordConnection(cursor)


def use_session(token: str, target_client: TestClient | None = None) -> TestClient:
    local_client = target_client or client
    local_client.cookies.set(dependencies.SESSION_COOKIE_NAME, token)
    return local_client


def patch_session_db(monkeypatch, cursor):
    monkeypatch.setattr(dependencies, "ensure_session_table", lambda: None)
    monkeypatch.setattr(dependencies, "get_db", lambda: password_db(cursor))


@pytest.mark.parametrize(
    "path",
    ["/api/users/2/reset-password", "/api/gallery/password"],
)
def test_password_management_endpoints_require_auth_and_admin(path):
    body = {"old_password": "old-password", "new_password": "new-password"}

    assert TestClient(app).post(path, json=body).status_code == 401

    visitor_token = cache_user("visitor-user")
    visitor = use_session(visitor_token, TestClient(app))
    assert visitor.post(path, json=body).status_code == 403


def test_change_own_password_revokes_sessions(monkeypatch):
    token = cache_user("owner-user")
    use_session(token)
    cursor = PasswordCursor(stored_password="old-password")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/password",
        json={"old_password": "old-password", "new_password": "new-password"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "reauthenticate": True}
    assert token not in dependencies._sessions
    assert token not in dependencies._session_expiries
    assert any(
        sql.startswith(f"UPDATE `{settings.users_table}` SET password")
        and params == ("new-password", "owner-user")
        for sql, params in cursor.executed
    )
    assert any(
        sql.startswith(f"DELETE FROM `{settings.sessions_table}`")
        and params == ("owner-user",)
        for sql, params in cursor.executed
    )


def test_change_own_password_keeps_validation_and_error_contract(monkeypatch):
    token = cache_user("owner-user")
    use_session(token)
    cursor = PasswordCursor(stored_password="old-password")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    wrong_old = client.post(
        "/api/users/password",
        json={"old_password": "wrong-password", "new_password": "new-password"},
    )
    short = client.post(
        "/api/users/password",
        json={"old_password": "old-password", "new_password": "1234567"},
    )
    spaced = client.post(
        "/api/users/password",
        json={"old_password": "old-password", "new_password": " new-password "},
    )

    password_limiter.reset("password:testclient:owner-user")
    assert wrong_old.status_code == 400
    assert wrong_old.json() == {"error": "旧密码错误"}
    assert short.status_code == 400
    assert short.json() == {"error": "请输入旧密码，新密码长度需为 8-128 个字符"}
    assert spaced.status_code == 400
    assert spaced.json() == {"error": "新密码首尾不能包含空格"}
    assert token in dependencies._sessions
    assert not any(sql.startswith("UPDATE") for sql, _ in cursor.executed)


def test_admin_resets_other_user_and_revokes_only_target_sessions(monkeypatch):
    admin_token = cache_user("admin-user", "admin")
    target_token = cache_user("target-user")
    other_token = cache_user("other-user")
    use_session(admin_token)
    cursor = PasswordCursor(target_username="target-user")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/42/reset-password",
        json={"new_password": "new-password"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert target_token not in dependencies._sessions
    assert admin_token in dependencies._sessions
    assert other_token in dependencies._sessions
    assert any(
        sql.startswith(f"UPDATE `{settings.users_table}` SET password")
        and params == ("new-password", 42)
        for sql, params in cursor.executed
    )
    assert any(
        sql.startswith(f"DELETE FROM `{settings.sessions_table}`")
        and params == ("target-user",)
        for sql, params in cursor.executed
    )


def test_admin_cannot_reset_own_password(monkeypatch):
    admin_token = cache_user("admin-user", "admin")
    use_session(admin_token)
    cursor = PasswordCursor(target_username="admin-user")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/42/reset-password",
        json={"new_password": "new-password"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "不能重置当前登录账号，请使用本人改密接口"
    }
    assert admin_token in dependencies._sessions
    assert not any(
        sql.startswith(("UPDATE", "DELETE")) for sql, _ in cursor.executed
    )


def test_admin_cannot_reset_own_account_with_different_username_case(monkeypatch):
    admin_token = cache_user("Admin-User", "admin")
    use_session(admin_token)
    cursor = PasswordCursor(target_username="admin-user")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/42/reset-password",
        json={"new_password": "new-password"},
    )

    assert response.status_code == 400
    assert admin_token in dependencies._sessions
    assert not any(
        sql.startswith(("UPDATE", "DELETE")) for sql, _ in cursor.executed
    )


def test_admin_reset_returns_404_for_missing_user(monkeypatch):
    admin_token = cache_user("admin-user", "admin")
    use_session(admin_token)
    cursor = PasswordCursor(target_username=None)
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/999/reset-password",
        json={"new_password": "new-password"},
    )

    assert response.status_code == 404
    assert response.json() == {"error": "user not found"}
    assert admin_token in dependencies._sessions


@pytest.mark.parametrize(
    ("new_password", "expected_error"),
    [
        ("1234567", "新密码长度需为 8-128 个字符"),
        ("x" * 129, "新密码长度需为 8-128 个字符"),
        (" new-password", "新密码首尾不能包含空格"),
        ("new-password ", "新密码首尾不能包含空格"),
    ],
)
def test_admin_reset_validates_password_shape(
    monkeypatch,
    new_password,
    expected_error,
):
    admin_token = cache_user("admin-user", "admin")
    use_session(admin_token)
    cursor = PasswordCursor(target_username="target-user")
    monkeypatch.setattr(users_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)

    response = client.post(
        "/api/users/42/reset-password",
        json={"new_password": new_password},
    )

    assert response.status_code == 400
    assert response.json() == {"error": expected_error}
    assert not any(sql.startswith("UPDATE") for sql, _ in cursor.executed)


def test_gallery_password_change_rejects_wrong_old_password(monkeypatch):
    admin_token = cache_user("admin-user", "admin", gallery_unlocked=True)
    use_session(admin_token)
    monkeypatch.setattr(
        gallery_router,
        "verify_page_password",
        lambda page_key, password: False,
    )

    response = client.post(
        "/api/gallery/password",
        json={"old_password": "wrong-password", "new_password": "new-gallery"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "旧密码错误"}
    assert dependencies._sessions[admin_token].gallery_unlocked is True


def test_gallery_password_change_clears_all_cached_and_persisted_unlocks(monkeypatch):
    admin_token = cache_user("admin-user", "admin", gallery_unlocked=True)
    unlocked_tokens = [
        cache_user("user-a", gallery_unlocked=True),
        cache_user("user-b", gallery_unlocked=True),
        cache_user("user-c", gallery_unlocked=False),
    ]
    use_session(admin_token)
    cursor = PasswordCursor()
    monkeypatch.setattr(gallery_router, "get_db", lambda: password_db(cursor))
    patch_session_db(monkeypatch, cursor)
    monkeypatch.setattr(
        gallery_router,
        "verify_page_password",
        lambda page_key, password: page_key == "gallery" and password == "old-gallery",
    )

    response = client.post(
        "/api/gallery/password",
        json={
            "old_password": "old-gallery",
            "new_password": "new-gallery",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "gallery_reauthenticate": True}
    assert all(
        user.gallery_unlocked is False for user in dependencies._sessions.values()
    )
    assert all(
        token in dependencies._sessions for token in [admin_token, *unlocked_tokens]
    )
    assert any(
        sql.startswith(f"INSERT INTO `{settings.page_password_table}`")
        and "ON DUPLICATE KEY UPDATE password" in sql
        and params == ("gallery", "new-gallery")
        for sql, params in cursor.executed
    )
    assert any(
        sql.startswith(f"UPDATE `{settings.sessions_table}` SET gallery_unlocked = 0")
        for sql, _ in cursor.executed
    )


@pytest.mark.parametrize(
    ("new_password", "expected_error"),
    [
        ("123", "新密码长度需为 4-128 个字符"),
        ("x" * 129, "新密码长度需为 4-128 个字符"),
        (" new-gallery", "新密码首尾不能包含空格"),
        ("new-gallery ", "新密码首尾不能包含空格"),
    ],
)
def test_gallery_password_change_validates_new_password(
    monkeypatch,
    new_password,
    expected_error,
):
    admin_token = cache_user("admin-user", "admin")
    use_session(admin_token)
    verify_called = False

    def verify(page_key, password):
        nonlocal verify_called
        verify_called = True
        return True

    monkeypatch.setattr(gallery_router, "verify_page_password", verify)

    response = client.post(
        "/api/gallery/password",
        json={"old_password": "old-gallery", "new_password": new_password},
    )

    assert response.status_code == 400
    assert response.json() == {"error": expected_error}
    assert verify_called is False
    assert dependencies._sessions[admin_token].gallery_unlocked is False


def test_gallery_password_change_is_rate_limited(monkeypatch):
    admin_token = cache_user("admin-user", "admin")
    use_session(admin_token)
    monkeypatch.setattr(
        gallery_router,
        "verify_page_password",
        lambda page_key, password: False,
    )

    for _ in range(gallery_limiter.limit):
        response = client.post(
            "/api/gallery/password",
            json={"old_password": "wrong", "new_password": "new-gallery"},
        )
        assert response.status_code == 400

    blocked = client.post(
        "/api/gallery/password",
        json={"old_password": "wrong", "new_password": "new-gallery"},
    )

    assert blocked.status_code == 429
    assert blocked.json() == {"error": "密码尝试过于频繁，请稍后再试"}
