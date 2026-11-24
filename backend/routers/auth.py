"""认证路由 - 登录/注册/状态"""
import hmac
import json
from fastapi import APIRouter, Request, Response
from ..database import get_db, get_config
from ..config import settings
from ..dependencies import (
    UserInfo, get_current_user,
    create_session, destroy_session,
    set_login_cookie, clear_login_cookie,
)
from ..security import get_client_ip, login_ip_limiter, login_limiter, registration_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status(request: Request):
    user = get_current_user(request)
    if user:
        return {"authenticated": True, "username": user.username, "role": user.role}
    return Response(
        content='{"authenticated": false}',
        status_code=401,
        media_type="application/json",
    )


@router.post("/login")
def auth_login(request: Request, body: dict = {}):
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    if not username or not password:
        return Response(
            content='{"error": "请输入用户名和密码"}',
            status_code=400,
            media_type="application/json",
        )

    client_ip = get_client_ip(request)
    rate_key = f"login:{client_ip}:{username.casefold()}"
    if not login_ip_limiter.allow(f"login-ip:{client_ip}") or not login_limiter.allow(rate_key):
        return Response(
            content='{"error": "登录尝试过于频繁，请稍后再试"}',
            status_code=429,
            media_type="application/json",
        )

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, role, disabled, password FROM `{settings.users_table}` "
                "WHERE username = %s LIMIT 1",
                (username,),
            )
            row = cursor.fetchone()

    if not row or not hmac.compare_digest(
        str(row[3]).encode("utf-8"), password.encode("utf-8")
    ):
        return Response(
            content='{"error": "用户名或密码错误"}',
            status_code=401,
            media_type="application/json",
        )
    if row[2]:  # disabled
        return Response(
            content='{"error": "账号已被禁用"}',
            status_code=403,
            media_type="application/json",
        )

    token = create_session(UserInfo(username=username, role=row[1]))
    login_limiter.reset(rate_key)
    
    # 记录最后登录时间
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE `{settings.users_table}` SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s",
                (row[0],)
            )
        conn.commit()

    resp = Response(
        content=json.dumps({"ok": True, "username": username, "role": row[1]}),
        media_type="application/json",
    )
    set_login_cookie(resp, token)
    return resp


@router.post("/register")
def auth_register(request: Request, body: dict = {}):
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", "")).strip()
    invite_code = str(body.get("invite_code", "")).strip()

    if not username or not password or not invite_code:
        return Response(
            content='{"error": "请填写所有字段"}',
            status_code=400,
            media_type="application/json",
        )
    if not registration_limiter.allow(f"register:{get_client_ip(request)}"):
        return Response(
            content='{"error": "注册尝试过于频繁，请稍后再试"}',
            status_code=429,
            media_type="application/json",
        )
    if len(username) < 2 or len(username) > 20:
        return Response(
            content='{"error": "用户名长度 2-20 个字符"}',
            status_code=400,
            media_type="application/json",
        )
    if len(password) < 4 or len(password) > 50:
        return Response(
            content='{"error": "密码长度 4-50 个字符"}',
            status_code=400,
            media_type="application/json",
        )

    # 校验邀请码
    valid_code = get_config("INVITE_CODE")
    if not valid_code or invite_code != valid_code:
        return Response(
            content='{"error": "邀请码无效"}',
            status_code=403,
            media_type="application/json",
        )

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM `{settings.users_table}` WHERE username = %s",
                (username,),
            )
            if cursor.fetchone():
                return Response(
                    content='{"error": "用户名已被注册"}',
                    status_code=409,
                    media_type="application/json",
                )
            cursor.execute(
                f"INSERT INTO `{settings.users_table}` (username, password, role) VALUES (%s, %s, 'visitor')",
                (username, password),
            )
            # 注册算做首次登录
            cursor.execute(
                f"UPDATE `{settings.users_table}` SET last_login_at = CURRENT_TIMESTAMP WHERE username = %s",
                (username,)
            )
        conn.commit()

    # 注册后自动登录
    registration_limiter.reset(f"register:{get_client_ip(request)}")
    token = create_session(UserInfo(username=username, role="visitor"))
    resp = Response(
        content=json.dumps({"ok": True, "username": username, "role": "visitor"}),
        media_type="application/json",
    )
    set_login_cookie(resp, token)
    return resp


@router.post("/logout")
def auth_logout(request: Request):
    deleted = destroy_session(request)
    response = Response(
        content=json.dumps({"ok": deleted, "session_deleted": deleted}),
        status_code=200 if deleted else 503,
        media_type="application/json",
    )
    clear_login_cookie(response)
    return response
