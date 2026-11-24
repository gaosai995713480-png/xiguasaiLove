"""点歌台路由 — 登录用户推荐歌曲"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from ..database import get_db
from ..config import settings
from ..dependencies import require_auth, require_role
from ..security import SlidingWindowLimiter, get_client_ip
from ..services.meting import MUSIC_PLATFORMS

router = APIRouter(prefix="/api", tags=["jukebox"])

_RATE_LIMIT = 5        # 每小时最多推荐次数
_RATE_WINDOW = 3600     # 窗口（秒）
_rate_limiter = SlidingWindowLimiter(_RATE_LIMIT, _RATE_WINDOW)


def _check_rate_limit(ip: str) -> bool:
    """原子检查并记录一次推荐请求。"""
    return _rate_limiter.allow(ip)


def _get_client_ip(request: Request) -> str:
    """获取客户端 IP；代理头仅在 TRUST_PROXY_HEADERS 开启时使用。"""
    return get_client_ip(request)[:45]


@router.get("/jukebox")
def list_requests(limit: int = 50, _=Depends(require_auth)):
    limit = max(1, min(limit, 100))
    table = settings.song_request_table
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, song_id, song_name, artist, platform, nickname, "
                f"message, likes, is_adopted, created_at "
                f"FROM `{table}` ORDER BY likes DESC, created_at DESC LIMIT %s",
                (limit,),
            )
            rows = cursor.fetchall()
    return [
        {
            "id": r[0], "song_id": r[1], "song_name": r[2], "artist": r[3],
            "platform": r[4], "nickname": r[5], "message": r[6],
            "likes": r[7], "is_adopted": bool(r[8]),
            "created_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]


@router.post("/jukebox")
def create_request(body: dict, request: Request, _=Depends(require_auth)):
    song_id = str(body.get("song_id", "")).strip()
    song_name = str(body.get("song_name", "")).strip()
    artist = str(body.get("artist", "")).strip()
    platform = str(body.get("platform") or "netease").strip()
    nickname = str(body.get("nickname", "")).strip() or "匿名访客"
    message = str(body.get("message", "")).strip()

    if not song_id or not song_name:
        return JSONResponse({"error": "song_id and song_name are required"}, status_code=400)
    if len(song_id) > 20:
        return JSONResponse({"error": "song_id 过长"}, status_code=400)
    if platform not in MUSIC_PLATFORMS:
        return JSONResponse({"error": "目前仅支持网易云音乐"}, status_code=400)

    # 长度限制
    nickname = nickname[:30]
    message = message[:100]
    song_name = song_name[:100]
    artist = artist[:100]

    client_ip = _get_client_ip(request)

    if not _check_rate_limit(client_ip):
        return JSONResponse(
            {"error": "推荐太频繁，请稍后再试", "rate_limited": True},
            status_code=429,
        )

    table = settings.song_request_table
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO `{table}` "
                f"(song_id, song_name, artist, platform, nickname, message, ip) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (song_id, song_name, artist, platform, nickname, message, client_ip),
            )
            row_id = cursor.lastrowid
        conn.commit()

    return {"ok": True, "id": row_id}


@router.post("/jukebox/like")
def like_request(body: dict, request: Request, _=Depends(require_auth)):
    try:
        request_id = int(body.get("id", 0))
    except (ValueError, TypeError):
        request_id = 0
    if request_id <= 0:
        return JSONResponse({"error": "invalid id"}, status_code=400)

    client_ip = _get_client_ip(request)
    table = settings.song_request_table
    like_table = f"{table}_likes"

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM `{table}` WHERE id = %s",
                (request_id,),
            )
            if not cursor.fetchone():
                return JSONResponse({"error": "not found"}, status_code=404)
            cursor.execute(
                f"INSERT IGNORE INTO `{like_table}` (request_id, ip) VALUES (%s, %s)",
                (request_id, client_ip),
            )
            if cursor.rowcount == 0:
                # 已点赞过
                cursor.execute(
                    f"SELECT likes FROM `{table}` WHERE id = %s", (request_id,)
                )
                row = cursor.fetchone()
                return {
                    "ok": True, "id": request_id,
                    "likes": row[0] if row else 0, "liked": False,
                }
            # 新点赞
            cursor.execute(
                f"UPDATE `{table}` SET likes = likes + 1 WHERE id = %s",
                (request_id,),
            )
            conn.commit()
            cursor.execute(
                f"SELECT likes FROM `{table}` WHERE id = %s", (request_id,)
            )
            row = cursor.fetchone()
    return {
        "ok": True, "id": request_id,
        "likes": row[0] if row else 0, "liked": True,
    }


@router.post("/jukebox/adopt")
def adopt_request(body: dict, _=Depends(require_role("admin"))):
    try:
        request_id = int(body.get("id", 0))
    except (ValueError, TypeError):
        request_id = 0
    if request_id <= 0:
        return JSONResponse({"error": "invalid id"}, status_code=400)

    table = settings.song_request_table
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT song_id, song_name, artist, platform, is_adopted "
                f"FROM `{table}` WHERE id = %s FOR UPDATE",
                (request_id,),
            )
            row = cursor.fetchone()
            if not row:
                return JSONResponse({"error": "not found"}, status_code=404)
            if row[4]:
                return JSONResponse({"error": "already adopted"}, status_code=409)

            # 插入到歌单
            cursor.execute(
                f"INSERT INTO `{settings.music_table}` "
                f"(song_name, artist, netease_id, platform) VALUES (%s, %s, %s, %s)",
                (row[1], row[2], row[0], row[3]),
            )
            # 标记已采纳
            cursor.execute(
                f"UPDATE `{table}` SET is_adopted = 1 WHERE id = %s",
                (request_id,),
            )
        conn.commit()
    return {"ok": True}


@router.delete("/jukebox")
def delete_request(id: int, _=Depends(require_role("admin"))):
    if id <= 0:
        return JSONResponse({"error": "invalid id"}, status_code=400)

    table = settings.song_request_table
    like_table = f"{table}_likes"
    with get_db() as conn:
        with conn.cursor() as cursor:
            # 先删除关联的点赞记录
            cursor.execute(
                f"DELETE FROM `{like_table}` WHERE request_id = %s", (id,)
            )
            # 再删除推荐记录
            cursor.execute(
                f"DELETE FROM `{table}` WHERE id = %s", (id,)
            )
            affected = cursor.rowcount
        conn.commit()
    if not affected:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True}
