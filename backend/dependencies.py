"""认证依赖 - 持久化 session cookie 认证 + 角色权限。"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Response

from .config import settings
from .database import ensure_session_table, get_db

SESSION_COOKIE_NAME = "love_session"

logger = logging.getLogger(__name__)


@dataclass
class UserInfo:
    username: str
    role: str  # 'admin' | 'visitor'
    gallery_unlocked: bool = False


# 进程内缓存只是性能优化；真正的令牌状态在 love_sessions 表中。
_sessions: dict[str, UserInfo] = {}
_session_expiries: dict[str, float] = {}
_persisted_tokens: set[str] = set()
_sessions_lock = threading.RLock()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cache_session(
    token: str,
    user: UserInfo,
    expires_at: float,
    *,
    persisted: bool = False,
) -> None:
    with _sessions_lock:
        _sessions[token] = user
        _session_expiries[token] = expires_at
        if persisted:
            _persisted_tokens.add(token)


def _drop_cached_session(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(token, None)
        _session_expiries.pop(token, None)
        _persisted_tokens.discard(token)


def _cached_session(token: str) -> UserInfo | None:
    with _sessions_lock:
        expires_at = _session_expiries.get(token)
        if expires_at is None or expires_at <= time.time():
            _sessions.pop(token, None)
            _session_expiries.pop(token, None)
            return None
        return _sessions.get(token)


def _load_session(token: str) -> UserInfo | None:
    """从持久化会话表恢复会话，并同步缓存。"""
    if not token:
        return None
    try:
        ensure_session_table()
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT s.username, s.role, s.gallery_unlocked, s.expires_at, u.disabled
                    FROM `{settings.sessions_table}` s
                    LEFT JOIN `{settings.users_table}` u ON u.username = s.username
                    WHERE s.token_hash = %s
                    LIMIT 1
                    """,
                    (_hash_token(token),),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                if row[4]:  # 账号被禁用
                    cursor.execute(
                        f"DELETE FROM `{settings.sessions_table}` WHERE token_hash = %s",
                        (_hash_token(token),),
                    )
                    conn.commit()
                    return None
                expires_at = row[3]
                if isinstance(expires_at, datetime):
                    expires_ts = expires_at.timestamp()
                else:
                    expires_ts = float(expires_at)
                if expires_ts <= time.time():
                    cursor.execute(
                        f"DELETE FROM `{settings.sessions_table}` WHERE token_hash = %s",
                        (_hash_token(token),),
                    )
                    conn.commit()
                    return None
                user = UserInfo(
                    username=row[0],
                    role=row[1],
                    gallery_unlocked=bool(row[2]),
                )
                _cache_session(token, user, expires_ts, persisted=True)
                return user
    except Exception:
        logger.warning("读取持久化会话失败", exc_info=True)
        return None


def get_session_token(request: Request) -> str:
    """从 cookie 中获取 session token。"""
    return request.cookies.get(SESSION_COOKIE_NAME, "")


def get_current_user(request: Request) -> UserInfo | None:
    """获取当前登录用户信息。"""
    if getattr(request.state, "_love_user_checked", False):
        return getattr(request.state, "_love_user", None)

    token = get_session_token(request)
    if not token:
        request.state._love_user_checked = True
        request.state._love_user = None
        return None
    cached = _cached_session(token)
    with _sessions_lock:
        is_persisted = token in _persisted_tokens
    # 测试/内存会话可以避免数据库依赖；真实登录会话每个请求都回查数据库，
    # 保证另一 worker 禁用账号或撤销会话后立即生效。
    user = _load_session(token) if is_persisted or cached is None else cached
    request.state._love_user_checked = True
    request.state._love_user = user
    return user


def get_user_from_token(token: str) -> UserInfo | None:
    """供 WebSocket 等没有 Request 的场景读取会话。"""
    token = (token or "").strip()
    if not token:
        return None
    cached = _cached_session(token)
    with _sessions_lock:
        is_persisted = token in _persisted_tokens
    return _load_session(token) if is_persisted or cached is None else cached


def is_authenticated(request: Request) -> bool:
    """检查是否已登录。"""
    return get_current_user(request) is not None


def require_auth(request: Request) -> None:
    """认证依赖：未登录则 401。"""
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def require_role(role: str):
    """权限依赖工厂：要求指定角色。"""
    def _checker(request: Request):
        user = get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="unauthorized")
        if user.role != role:
            raise HTTPException(status_code=403, detail="权限不足")
    return _checker


def require_gallery_access(request: Request) -> None:
    """要求当前登录会话已解锁画廊。"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    if not user.gallery_unlocked:
        raise HTTPException(status_code=403, detail="画廊未解锁")


def create_session(user_info: UserInfo, ttl_seconds: int | None = None) -> str:
    """创建新 session，并同时写入数据库和进程缓存。"""
    token = secrets.token_urlsafe(32)
    ttl = int(ttl_seconds or settings.session_ttl_seconds)
    expires_at = datetime.now() + timedelta(seconds=ttl)
    ensure_session_table()
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO `{settings.sessions_table}`
                    (token_hash, username, role, gallery_unlocked, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    _hash_token(token),
                    user_info.username,
                    user_info.role,
                    1 if user_info.gallery_unlocked else 0,
                    expires_at,
                ),
            )
        conn.commit()
    _cache_session(token, user_info, expires_at.timestamp(), persisted=True)
    return token


def destroy_session(request: Request) -> bool:
    """销毁 session；返回是否成功删除持久化记录。"""
    token = get_session_token(request)
    if not token:
        return True
    _drop_cached_session(token)
    try:
        ensure_session_table()
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM `{settings.sessions_table}` WHERE token_hash = %s",
                    (_hash_token(token),),
                )
            conn.commit()
        return True
    except Exception:
        logger.warning("删除持久化会话失败", exc_info=True)
        return False


def revoke_user_sessions(username: str) -> None:
    """撤销某个用户的全部会话，用于禁用账号和密码变更。"""
    with _sessions_lock:
        tokens = [
            token for token, user in _sessions.items()
            if user.username == username
        ]
    for token in tokens:
        _drop_cached_session(token)
    try:
        ensure_session_table()
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM `{settings.sessions_table}` WHERE username = %s",
                    (username,),
                )
            conn.commit()
    except Exception:
        logger.warning("撤销用户会话失败: %s", username, exc_info=True)


def revoke_gallery_access() -> None:
    """清除所有会话的画廊解锁状态，但保留登录会话。"""
    with _sessions_lock:
        for user in _sessions.values():
            user.gallery_unlocked = False
    try:
        ensure_session_table()
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE `{settings.sessions_table}`
                    SET gallery_unlocked = 0
                    """
                )
            conn.commit()
    except Exception:
        logger.warning("撤销会话画廊访问状态失败", exc_info=True)
        raise


def set_gallery_unlocked(request: Request, unlocked: bool = True) -> None:
    """更新当前会话的画廊解锁状态，并持久化。"""
    token = get_session_token(request)
    user = get_current_user(request)
    if not token or not user:
        return
    user.gallery_unlocked = bool(unlocked)
    _cache_session(
        token,
        user,
        _session_expiries.get(token, time.time() + settings.session_ttl_seconds),
        persisted=True,
    )
    try:
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE `{settings.sessions_table}`
                    SET gallery_unlocked = %s
                    WHERE token_hash = %s
                    """,
                    (1 if unlocked else 0, _hash_token(token)),
                )
            conn.commit()
    except Exception:
        logger.warning("更新会话画廊状态失败", exc_info=True)


def set_login_cookie(response: Response, token: str) -> None:
    """设置登录 cookie。"""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_seconds,
    )


def clear_login_cookie(response: Response) -> None:
    """清除登录 cookie。"""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
