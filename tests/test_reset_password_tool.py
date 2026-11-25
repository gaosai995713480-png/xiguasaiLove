from __future__ import annotations

from contextlib import contextmanager

import pytest

from tools import reset_password


class FakeCursor:
    def __init__(self, *, fetch_results=None):
        self.calls: list[tuple[str, tuple | None]] = []
        self._fetch_results = list(fetch_results or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self._fetch_results.pop(0) if self._fetch_results else None


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commit_count = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_count += 1


def make_db_factory(connection):
    @contextmanager
    def factory():
        yield connection

    return factory


@pytest.fixture(autouse=True)
def stable_table_names(monkeypatch):
    monkeypatch.setattr(reset_password.settings, "users_table", "love_users")
    monkeypatch.setattr(reset_password.settings, "sessions_table", "love_sessions")
    monkeypatch.setattr(
        reset_password.settings,
        "page_password_table",
        "love_page_password",
    )


def test_reset_user_password_updates_password_and_revokes_sessions():
    cursor = FakeCursor(fetch_results=[(7,)])
    connection = FakeConnection(cursor)

    target = reset_password.reset_user_password(
        "admin",
        "new-password",
        db_factory=make_db_factory(connection),
    )

    assert target == "admin"
    assert connection.commit_count == 1
    assert len(cursor.calls) == 3

    select_sql, select_params = cursor.calls[0]
    assert "SELECT id FROM `love_users`" in select_sql
    assert select_params == ("admin",)

    update_sql, update_params = cursor.calls[1]
    assert "UPDATE `love_users` SET password = %s" in update_sql
    assert update_params == ("new-password", "admin")
    assert "new-password" not in update_sql

    delete_sql, delete_params = cursor.calls[2]
    assert "DELETE FROM `love_sessions` WHERE username = %s" in delete_sql
    assert delete_params == ("admin",)


def test_reset_user_password_missing_user_does_not_write_or_commit():
    cursor = FakeCursor(fetch_results=[None])
    connection = FakeConnection(cursor)

    with pytest.raises(reset_password.TargetNotFoundError, match="用户不存在"):
        reset_password.reset_user_password(
            "missing",
            "new-password",
            db_factory=make_db_factory(connection),
        )

    assert len(cursor.calls) == 1
    assert connection.commit_count == 0


def test_reset_gallery_password_upserts_and_locks_all_sessions():
    cursor = FakeCursor()
    connection = FakeConnection(cursor)

    target = reset_password.reset_gallery_password(
        "gallery-password",
        db_factory=make_db_factory(connection),
    )

    assert target == "gallery"
    assert connection.commit_count == 1
    assert len(cursor.calls) == 2

    upsert_sql, upsert_params = cursor.calls[0]
    assert "INSERT INTO `love_page_password`" in upsert_sql
    assert "ON DUPLICATE KEY UPDATE password = VALUES(password)" in upsert_sql
    assert upsert_params == ("gallery", "gallery-password")
    assert "gallery-password" not in upsert_sql

    lock_sql, lock_params = cursor.calls[1]
    assert "UPDATE `love_sessions` SET gallery_unlocked = 0" in lock_sql
    assert lock_params is None


@pytest.mark.parametrize(
    "password",
    [
        "",
        "abc",
        "a" * 129,
        " password",
        "password ",
        "    ",
    ],
)
def test_validate_password_rejects_invalid_values(password):
    with pytest.raises(reset_password.PasswordResetError):
        reset_password.validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        "abcd",
        "a" * 128,
        "internal space",
    ],
)
def test_validate_password_accepts_boundaries_and_internal_spaces(password):
    reset_password.validate_password(password)


def test_prompt_for_password_requires_two_matching_entries():
    values = iter(["new-password", "new-password"])
    assert reset_password.prompt_for_password(lambda _prompt: next(values)) == "new-password"

    values = iter(["new-password", "different-password"])
    with pytest.raises(reset_password.PasswordResetError, match="不一致"):
        reset_password.prompt_for_password(lambda _prompt: next(values))


def test_parser_rejects_user_and_gallery_together():
    parser = reset_password.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--user", "admin", "--gallery"])
    assert exc.value.code == 2


def test_parser_has_no_password_argument():
    parser = reset_password.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--user", "admin", "--password", "secret"])
    assert exc.value.code == 2


def test_cli_success_never_prints_password(capsys):
    cursor = FakeCursor(fetch_results=[(7,)])
    connection = FakeConnection(cursor)
    values = iter(["secret-password", "secret-password"])

    code = reset_password.main(
        ["--user", "admin"],
        password_reader=lambda _prompt: next(values),
        db_factory=make_db_factory(connection),
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "用户 admin 已重置"
    assert "secret-password" not in captured.out
    assert "secret-password" not in captured.err


def test_cli_missing_user_returns_nonzero_and_clear_error(capsys):
    cursor = FakeCursor(fetch_results=[None])
    connection = FakeConnection(cursor)
    values = iter(["secret-password", "secret-password"])

    code = reset_password.main(
        ["--user", "missing"],
        password_reader=lambda _prompt: next(values),
        db_factory=make_db_factory(connection),
    )

    captured = capsys.readouterr()
    assert code != 0
    assert "用户不存在" in captured.err
    assert "secret-password" not in captured.err


def test_cli_database_error_returns_nonzero_without_leaking_password(capsys):
    @contextmanager
    def broken_db():
        raise RuntimeError("connection failed secret-password")
        yield

    values = iter(["secret-password", "secret-password"])
    code = reset_password.main(
        ["--gallery"],
        password_reader=lambda _prompt: next(values),
        db_factory=broken_db,
    )

    captured = capsys.readouterr()
    assert code != 0
    assert "数据库操作失败" in captured.err
    assert "secret-password" not in captured.err
