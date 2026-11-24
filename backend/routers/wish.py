"""星空许愿路由"""
import math

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..database import get_db
from ..config import settings
from ..dependencies import require_auth

router = APIRouter(prefix="/api", tags=["wish"])


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


@router.get("/wishes")
def list_wishes(_=Depends(require_auth)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, content, x, y, color, created_at FROM `{settings.wish_table}` ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
    return [
        {
            "id": r[0], "content": r[1], "x": r[2], "y": r[3],
            "color": r[4], "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


@router.post("/wishes")
def create_wish(body: dict, _=Depends(require_auth)):
    content = str(body.get("content", "")).strip()
    color = str(body.get("color", "#ffd700")).strip()
    if not content:
        return _error("content required", 400)
    if len(content) > 200:
        return _error("content too long (max 200)", 400)
    try:
        x = float(body.get("x", 0.5))
        y = float(body.get("y", 0.5))
    except (TypeError, ValueError):
        return _error("invalid coordinates", 400)
    if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1) or not (0 <= y <= 1):
        return _error("coordinates must be between 0 and 1", 400)
    if len(color) > 20:
        return _error("color too long (max 20)", 400)

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO `{settings.wish_table}` (content, x, y, color) VALUES (%s, %s, %s, %s)",
                (content, x, y, color),
            )
            row_id = cursor.lastrowid
        conn.commit()
    return {"ok": True, "id": row_id}
