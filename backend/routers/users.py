"""用户管理路由 - 管理员专属"""
import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from ..config import settings
from ..database import get_db, get_config, set_config
from ..dependencies import (
    clear_login_cookie,
    get_current_user,
    require_auth,
    require_role,
    revoke_user_sessions,
)
from ..security import get_client_ip, password_limiter

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(_=Depends(require_role("admin"))):
    """获取所有用户列表"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, username, role, disabled, created_at, last_login_at FROM `{settings.users_table}` ORDER BY id"
            )
            rows = cursor.fetchall()
    return [
        {
            "id": r[0],
            "username": r[1],
            "role": r[2],
            "disabled": bool(r[3]),
            "created_at": str(r[4]),
            "last_login_at": str(r[5]) if r[5] else None,
        }
        for r in rows
    ]


@router.post("/{user_id}/toggle")
def toggle_user(user_id: int, _=Depends(require_role("admin"))):
    """禁用/启用用户（不允许禁用 admin）"""
    username = ""
    disabled = 0
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT username, role FROM `{settings.users_table}` WHERE id = %s",
                (user_id,),
            )
            target = cursor.fetchone()
            if not target:
                return JSONResponse({"error": "user not found"}, status_code=404)
            if target[1] == "admin":
                return JSONResponse({"error": "不允许修改管理员状态"}, status_code=400)
            username = target[0]
            cursor.execute(
                f"UPDATE `{settings.users_table}` SET disabled = NOT disabled WHERE id = %s AND role != 'admin'",
                (user_id,),
            )
            cursor.execute(
                f"SELECT disabled FROM `{settings.users_table}` WHERE id = %s",
                (user_id,),
            )
            disabled = int(cursor.fetchone()[0])
        conn.commit()
    if disabled:
        revoke_user_sessions(username)
    return {"ok": True}


@router.post("/password")
def change_own_password(
    body: dict,
    request: Request,
    response: Response,
    _=Depends(require_auth),
):
    """修改当前登录用户密码，并撤销该用户的全部会话。"""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    old_password = str(body.get("old_password", "")).strip()
    raw_new_password = str(body.get("new_password", ""))
    new_password = raw_new_password.strip()
    if raw_new_password != new_password:
        return JSONResponse(
            {"error": "新密码首尾不能包含空格"},
            status_code=400,
        )
    if not old_password or len(new_password) < 8 or len(new_password) > 128:
        return JSONResponse(
            {"error": "请输入旧密码，新密码长度需为 8-128 个字符"},
            status_code=400,
        )

    rate_key = f"password:{get_client_ip(request)}:{user.username}"
    if not password_limiter.allow(rate_key):
        return JSONResponse({"error": "改密尝试过于频繁，请稍后再试"}, status_code=429)

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT password FROM `{settings.users_table}` WHERE username = %s LIMIT 1",
                (user.username,),
            )
            row = cursor.fetchone()
            if not row or not hmac.compare_digest(
                str(row[0]).encode("utf-8"), old_password.encode("utf-8")
            ):
                return JSONResponse({"error": "旧密码错误"}, status_code=400)
            cursor.execute(
                f"UPDATE `{settings.users_table}` SET password = %s WHERE username = %s",
                (new_password, user.username),
            )
        conn.commit()

    password_limiter.reset(rate_key)
    revoke_user_sessions(user.username)
    clear_login_cookie(response)
    return {"ok": True, "reauthenticate": True}


@router.get("/invite-code")
def get_invite_code(_=Depends(require_role("admin"))):
    """获取当前邀请码"""
    return {"code": get_config("INVITE_CODE") or ""}


@router.post("/invite-code")
def update_invite_code(body: dict, _=Depends(require_role("admin"))):
    """修改邀请码"""
    code = str(body.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "邀请码不能为空"}
    set_config("INVITE_CODE", code)
    return {"ok": True}
