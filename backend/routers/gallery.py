"""画廊路由 - 密码验证"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import settings
from ..database import get_db, verify_page_password
from ..dependencies import (
    require_auth,
    require_role,
    revoke_gallery_access,
    set_gallery_unlocked,
)
from ..security import gallery_limiter, get_client_ip

router = APIRouter(prefix="/api/gallery", tags=["gallery"])


class VerifyRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/verify")
def verify_gallery_password(body: VerifyRequest, request: Request, _=Depends(require_auth)):
    """验证画廊密码"""
    rate_key = f"gallery:{get_client_ip(request)}"
    if not gallery_limiter.allow(rate_key):
        return JSONResponse(
            {"error": "密码尝试过于频繁，请稍后再试"},
            status_code=429,
        )
    if verify_page_password("gallery", body.password):
        set_gallery_unlocked(request, True)
        gallery_limiter.reset(rate_key)
        return {"ok": True}
    return {"ok": False, "error": "密码错误"}


@router.post("/password")
def change_gallery_password(
    body: ChangePasswordRequest,
    request: Request,
    _=Depends(require_role("admin")),
):
    """管理员更换画廊密码，并要求所有会话重新验证。"""
    raw_new_password = body.new_password
    new_password = raw_new_password.strip()
    if raw_new_password != new_password:
        return JSONResponse(
            {"error": "新密码首尾不能包含空格"},
            status_code=400,
        )
    if len(new_password) < 4 or len(new_password) > 128:
        return JSONResponse(
            {"error": "新密码长度需为 4-128 个字符"},
            status_code=400,
        )
    if not body.old_password:
        return JSONResponse({"error": "旧密码不能为空"}, status_code=400)

    rate_key = f"gallery:{get_client_ip(request)}"
    if not gallery_limiter.allow(rate_key):
        return JSONResponse(
            {"error": "密码尝试过于频繁，请稍后再试"},
            status_code=429,
        )

    if not verify_page_password("gallery", body.old_password):
        return JSONResponse({"error": "旧密码错误"}, status_code=400)

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO `{settings.page_password_table}` (page_key, password)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE password = VALUES(password)
                """,
                ("gallery", new_password),
            )
        conn.commit()

    revoke_gallery_access()
    gallery_limiter.reset(rate_key)
    return {"ok": True, "gallery_reauthenticate": True}
