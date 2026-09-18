"""某一天的生活痕迹聚合"""
import datetime
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user, require_auth
from ..services.oss_storage import get_oss_bucket
from ..utils import aligned_expires, photo_sort_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["day"])

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def parse_iso_date(value: str) -> datetime.date | None:
    if not value or not _ISO_DATE.fullmatch(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        return text[:10] if "T" in text or len(text) >= 10 else text
    text = str(value)
    return text[:10] if text else None


def _photo_urls(filename: str, raw_url: str, expires: int) -> tuple[str, str]:
    bucket = get_oss_bucket()
    if not bucket:
        return raw_url, raw_url
    try:
        url = bucket.sign_url("GET", f"photos/{filename}", expires, slash_safe=True)
        thumb = bucket.sign_url(
            "GET",
            f"photos/{filename}",
            expires,
            slash_safe=True,
            params={"x-oss-process": "image/resize,w_500,m_lfit"},
        )
        return url, thumb
    except Exception:
        logger.warning("为相册照片签名失败: %s", filename, exc_info=True)
        return raw_url, raw_url


@router.get("/day/{day}")
def get_day(day: str, request: Request, _=Depends(require_auth)):
    parsed = parse_iso_date(day)
    if parsed is None:
        return _error("invalid date", 400)

    day_text = parsed.isoformat()
    user = get_current_user(request)
    gallery_unlocked = bool(user and user.gallery_unlocked)

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, event_date, title, content, photo_url, icon FROM `{settings.timeline_table}` WHERE event_date = %s ORDER BY id ASC",
                (day_text,),
            )
            timeline_rows = cursor.fetchall()

            cursor.execute(
                f"SELECT id, mood_date, emoji, note, level FROM `{settings.mood_table}` WHERE mood_date = %s",
                (day_text,),
            )
            mood_row = cursor.fetchone()

            cursor.execute(
                f"SELECT id, title, note, photo_url, lat, lng, visit_date FROM `{settings.map_table}` WHERE visit_date = %s ORDER BY id ASC",
                (day_text,),
            )
            marker_rows = cursor.fetchall()

            photos_map: dict[int, list[str]] = {}
            marker_ids = [row[0] for row in marker_rows]
            if marker_ids:
                placeholders = ",".join(["%s"] * len(marker_ids))
                cursor.execute(
                    f"SELECT marker_id, photo_url FROM `{settings.map_photos_table}` WHERE marker_id IN ({placeholders}) ORDER BY sort_order, id",
                    marker_ids,
                )
                for marker_id, photo_url in cursor.fetchall():
                    photos_map.setdefault(marker_id, []).append(photo_url)

            photo_rows = []
            if gallery_unlocked:
                cursor.execute(
                    "SELECT id, filename, oss_url, description, created_at FROM love_photos WHERE DATE(created_at) = %s",
                    (day_text,),
                )
                photo_rows = list(cursor.fetchall())

    timeline = [
        {
            "id": row[0],
            "event_date": _iso(row[1]),
            "title": row[2],
            "content": row[3],
            "photo_url": row[4],
            "icon": row[5] or "💕",
        }
        for row in timeline_rows
    ]

    mood = None
    if mood_row:
        mood = {
            "id": mood_row[0],
            "mood_date": _iso(mood_row[1]),
            "emoji": mood_row[2],
            "note": mood_row[3],
            "level": mood_row[4],
        }

    places = [
        {
            "id": row[0],
            "title": row[1],
            "note": row[2],
            "photo_url": row[3],
            "lat": row[4],
            "lng": row[5],
            "visit_date": _iso(row[6]),
            "photos": photos_map.get(row[0], []),
        }
        for row in marker_rows
    ]

    photos = []
    if gallery_unlocked and photo_rows:
        expires = aligned_expires()
        sorted_rows = sorted(photo_rows, key=lambda row: photo_sort_key(Path(row[1])))
        for row in sorted_rows:
            url, thumbnail_url = _photo_urls(row[1], row[2], expires)
            created = row[4]
            photos.append(
                {
                    "id": row[0],
                    "filename": row[1],
                    "url": url,
                    "thumbnail_url": thumbnail_url,
                    "description": row[3] or "",
                    "created_at": created.strftime("%Y-%m-%d %H:%M:%S") if created else "",
                }
            )

    return {
        "date": day_text,
        "timeline": timeline,
        "mood": mood,
        "places": places,
        "photos": photos,
        "gallery_unlocked": gallery_unlocked,
    }
