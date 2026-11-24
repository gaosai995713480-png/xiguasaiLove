"""画廊路由 - 密码验证"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..database import verify_page_password
from ..dependencies import require_auth, set_gallery_unlocked
from ..security import gallery_limiter, get_client_ip

router = APIRouter(prefix="/api/gallery", tags=["gallery"])


class VerifyRequest(BaseModel):
    password: str


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
