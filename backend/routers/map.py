"""恋爱地图路由"""
import datetime
import logging
import math
import time
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..database import get_db
from ..config import settings
from ..dependencies import require_auth, require_role
from ..utils import sanitize_upload_filename, is_image_filename
from ..services.oss_storage import (
    delete_from_oss,
    get_oss_bucket,
    get_oss_domain,
    upload_to_oss,
)

router = APIRouter(prefix="/api", tags=["map"])
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _normalize_photo_urls(raw_photos) -> list[str]:
    if not isinstance(raw_photos, list):
        return []
    photos = []
    for item in raw_photos:
        url = str(item or "").strip()
        if url:
            photos.append(url)
    return photos


def _parse_date(value: str) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_coordinates(body: dict) -> tuple[float, float] | None:
    if "lat" not in body or "lng" not in body:
        return None
    try:
        lat = float(body["lat"])
        lng = float(body["lng"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None
    return lat, lng


def _map_oss_key(url: str) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.netloc:
        configured = urlparse(get_oss_domain())
        if not configured.netloc or parsed.netloc != configured.netloc:
            return None
        path = unquote(parsed.path)
    else:
        path = unquote(text)
    path = path.lstrip("/").split("?", 1)[0]
    key = path
    parts = PurePosixPath(key).parts
    if len(parts) != 2 or parts[0] != "map" or parts[1] in {"", ".", ".."}:
        return None
    return key


def _referenced_map_keys() -> set[str] | None:
    """返回仍被任一足迹引用的 OSS key；查询失败时返回 None 并禁止清理。"""
    try:
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT photo_url FROM `{settings.map_photos_table}`
                    WHERE photo_url IS NOT NULL AND photo_url <> ''
                    UNION
                    SELECT photo_url FROM `{settings.map_table}`
                    WHERE photo_url IS NOT NULL AND photo_url <> ''
                    """
                )
                urls = [row[0] for row in (cursor.fetchall() or []) if row]
    except Exception:
        logger.warning("读取足迹媒体引用失败，跳过 OSS 清理", exc_info=True)
        return None
    return {key for url in urls if (key := _map_oss_key(url))}


def _cleanup_map_media(urls: list[str]) -> int:
    keys = {key for url in urls if (key := _map_oss_key(url))}
    if not keys or not get_oss_bucket():
        return 0
    referenced = _referenced_map_keys()
    if referenced is None:
        return 0
    deleted = 0
    for key in keys - referenced:
        if delete_from_oss(key):
            deleted += 1
    return deleted


def _marker_media_urls(cursor, marker_id: int) -> list[str]:
    cursor.execute(
        f"SELECT photo_url FROM `{settings.map_table}` WHERE id = %s",
        (marker_id,),
    )
    row = cursor.fetchone()
    urls = [row[0]] if row and row[0] else []
    cursor.execute(
        f"SELECT photo_url FROM `{settings.map_photos_table}` WHERE marker_id = %s",
        (marker_id,),
    )
    urls.extend(row[0] for row in (cursor.fetchall() or []) if row and row[0])
    return urls


def _marker_exists(cursor, row_id: int) -> bool:
    cursor.execute(
        f"SELECT 1 FROM `{settings.map_table}` WHERE id = %s",
        (row_id,),
    )
    return cursor.fetchone() is not None


@router.post("/map/upload")
async def upload_map_photo(request: Request, _=Depends(require_role("admin"))):
    """上传足迹照片到 OSS map/ 前缀下"""
    file_name = request.headers.get("X-File-Name", "").strip()
    file_name = unquote(file_name)
    safe_name = sanitize_upload_filename(file_name)

    if not safe_name or not is_image_filename(safe_name):
        return JSONResponse({"error": "invalid file name"}, status_code=400)

    file_data = await request.body()
    if not file_data:
        return JSONResponse({"error": "empty file"}, status_code=400)

    # 加时间戳防重名
    ts = int(time.time() * 1000)
    dot_idx = safe_name.rfind('.')
    if dot_idx > 0:
        safe_name = f"{safe_name[:dot_idx]}_{ts}{safe_name[dot_idx:]}"
    else:
        safe_name = f"{safe_name}_{ts}"

    success = upload_to_oss(safe_name, file_data, prefix="map")
    if success:
        domain = get_oss_domain()
        url = f"{domain}/map/{safe_name}"
        return {"ok": True, "url": url, "name": safe_name}
    return _error("upload failed", 500)


@router.post("/map/upload/cleanup")
def cleanup_map_uploads(body: dict, _=Depends(require_role("admin"))):
    names = body.get("names", [])
    if not isinstance(names, list):
        return _error("invalid names", 400)

    if not get_oss_bucket():
        return {"ok": True, "deleted": 0}
    referenced = _referenced_map_keys()
    if referenced is None:
        return _error("cannot verify media references", 500)

    deleted = 0
    for item in names:
        raw_name = str(item or "").strip()
        safe_name = sanitize_upload_filename(raw_name)
        if not safe_name or not is_image_filename(safe_name) or raw_name != safe_name:
            continue
        key = f"map/{safe_name}"
        if key in referenced:
            continue
        if delete_from_oss(key):
            deleted += 1
    return {"ok": True, "deleted": deleted}


@router.get("/map")
def list_markers(_=Depends(require_auth)):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT id, title, note, photo_url, lat, lng, visit_date, created_at FROM `{settings.map_table}` ORDER BY visit_date DESC"
            )
            rows = cursor.fetchall()

            # 查所有照片
            cursor.execute(
                f"SELECT marker_id, photo_url FROM `{settings.map_photos_table}` ORDER BY sort_order, id"
            )
            photo_rows = cursor.fetchall()

    # 按 marker_id 分组
    photos_map = {}
    for pr in photo_rows:
        photos_map.setdefault(pr[0], []).append(pr[1])

    return [
        {
            "id": r[0], "title": r[1], "note": r[2], "photo_url": r[3],
            "lat": r[4], "lng": r[5],
            "visit_date": r[6].isoformat() if r[6] else None,
            "created_at": r[7].isoformat() if r[7] else None,
            "photos": photos_map.get(r[0], []),
        }
        for r in rows
    ]


@router.post("/map")
def create_marker(body: dict, _=Depends(require_role("admin"))):
    title = str(body.get("title", "")).strip()
    note = str(body.get("note", "")).strip()
    visit_date = str(body.get("visit_date", "")).strip()
    photos = _normalize_photo_urls(body.get("photos", []))
    coordinates = _parse_coordinates(body)
    if coordinates is None:
        return _error("invalid coordinates", 400)
    lat, lng = coordinates

    if not title:
        return _error("title is required", 400)
    if len(title) > 100:
        return _error("title too long (max 100)", 400)
    if len(note) > 10000:
        return _error("note too long (max 10000)", 400)
    if visit_date and _parse_date(visit_date) is None:
        return _error("invalid visit_date", 400)
    if any(len(url) > 500 for url in photos):
        return _error("photo_url too long (max 500)", 400)

    # 第一张作为封面
    cover = photos[0] if photos else ""

    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO `{settings.map_table}` (title, note, photo_url, lat, lng, visit_date) VALUES (%s, %s, %s, %s, %s, %s)",
                (title, note, cover, lat, lng, visit_date or None),
            )
            row_id = cursor.lastrowid
            # 插入照片
            for i, url in enumerate(photos):
                cursor.execute(
                    f"INSERT INTO `{settings.map_photos_table}` (marker_id, photo_url, sort_order) VALUES (%s, %s, %s)",
                    (row_id, url, i),
                )
        conn.commit()
    return {"ok": True, "id": row_id}


@router.put("/map")
def update_marker(body: dict, _=Depends(require_role("admin"))):
    try:
        row_id = int(body.get("id", 0))
    except (ValueError, TypeError):
        row_id = 0
    if row_id <= 0:
        return _error("invalid id", 400)

    title = str(body.get("title", "")).strip()
    note = str(body.get("note", "")).strip()
    visit_date = str(body.get("visit_date", "")).strip()
    photos = _normalize_photo_urls(body.get("photos", []))
    coordinates = _parse_coordinates(body)
    if coordinates is None:
        return _error("invalid coordinates", 400)
    lat, lng = coordinates

    if not title:
        return _error("title is required", 400)
    if len(title) > 100:
        return _error("title too long (max 100)", 400)
    if len(note) > 10000:
        return _error("note too long (max 10000)", 400)
    if visit_date and _parse_date(visit_date) is None:
        return _error("invalid visit_date", 400)
    if any(len(url) > 500 for url in photos):
        return _error("photo_url too long (max 500)", 400)

    cover = photos[0] if photos else ""
    with get_db() as conn:
        with conn.cursor() as cursor:
            if not _marker_exists(cursor, row_id):
                return _error("not found", 404)
            old_urls = _marker_media_urls(cursor, row_id)
            cursor.execute(
                f"UPDATE `{settings.map_table}` SET title=%s, note=%s, photo_url=%s, lat=%s, lng=%s, visit_date=%s WHERE id=%s",
                (title, note, cover, lat, lng, visit_date or None, row_id),
            )
            # 先删旧照片再插新照片
            cursor.execute(
                f"DELETE FROM `{settings.map_photos_table}` WHERE marker_id = %s", (row_id,)
            )
            for i, url in enumerate(photos):
                cursor.execute(
                    f"INSERT INTO `{settings.map_photos_table}` (marker_id, photo_url, sort_order) VALUES (%s, %s, %s)",
                    (row_id, url, i),
                )
        conn.commit()
    removed_urls = [url for url in old_urls if url not in set(photos)]
    _cleanup_map_media(removed_urls)
    return {"ok": True}


@router.delete("/map")
def delete_marker(id: int, _=Depends(require_role("admin"))):
    if id <= 0:
        return _error("invalid id", 400)
    with get_db() as conn:
        with conn.cursor() as cursor:
            if not _marker_exists(cursor, id):
                return _error("not found", 404)
            media_urls = _marker_media_urls(cursor, id)
            # 先删照片再删主记录
            cursor.execute(
                f"DELETE FROM `{settings.map_photos_table}` WHERE marker_id = %s", (id,)
            )
            cursor.execute(
                f"DELETE FROM `{settings.map_table}` WHERE id = %s", (id,)
            )
        conn.commit()
    _cleanup_map_media(media_urls)
    return {"ok": True}
