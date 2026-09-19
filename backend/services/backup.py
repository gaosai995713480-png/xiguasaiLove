"""管理员回忆备份：结构化数据 + 可读年表 + 照片文件。不含密钥。"""
from __future__ import annotations

import json
import logging
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import settings
from ..database import get_db
from ..utils import sanitize_upload_filename
from .oss_storage import get_oss_bucket

logger = logging.getLogger(__name__)

EXPORT_VERSION = 1
EXPORT_TTL = timedelta(hours=2)
PACK_TIMEOUT = timedelta(minutes=30)
FOLDER_PREFIX = "xiguasai-memory"
MEDIA_FETCH_WORKERS = 8
_STORE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif",
    ".bmp", ".tif", ".tiff", ".mp4", ".mov", ".m4v", ".mp3", ".aac", ".m4a",
}

_SECRET_TABLE_HINTS = (
    "love_config",
    "love_users",
    "love_page_password",
    "ai_messages",
    "ai_conversations",
)

_lock = threading.Lock()
_job: "ExportJob | None" = None


def get_export_dir() -> Path:
    path = settings.base_dir / "tmp" / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class ExportProgress:
    current: int = 0
    total: int = 0
    message: str = ""


@dataclass
class ExportJob:
    id: str
    status: str
    filename: str
    created_at: datetime
    expires_at: datetime
    progress: ExportProgress = field(default_factory=ExportProgress)
    zip_path: Path | None = None
    error: str | None = None
    stats: dict = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "filename": self.filename,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "error": self.error,
            "progress": {
                "current": self.progress.current,
                "total": self.progress.total,
                "message": self.progress.message,
            },
            "stats": self.stats,
            "file_size": self.file_size(),
        }

    def file_size(self) -> int:
        if self.status != "done" or not self.zip_path:
            return 0
        try:
            return self.zip_path.stat().st_size if self.zip_path.is_file() else 0
        except OSError:
            return 0


def reset_jobs() -> None:
    """测试用：清空当前任务。"""
    global _job
    with _lock:
        _job = None


def current_job() -> ExportJob | None:
    with _lock:
        _expire_locked()
        return _job


def start_export() -> ExportJob:
    global _job
    with _lock:
        _expire_locked()
        if _job and _job.status == "packing":
            if datetime.now() - _job.created_at < PACK_TIMEOUT:
                return _job
            _job.status = "failed"
            _job.error = "导出超时，请重试"
        stamp = date.today().isoformat()
        job_id = uuid.uuid4().hex
        job = ExportJob(
            id=job_id,
            status="packing",
            filename=f"{FOLDER_PREFIX}-{stamp}.zip",
            created_at=datetime.now(),
            expires_at=datetime.now() + EXPORT_TTL,
            progress=ExportProgress(message="正在收集回忆"),
        )
        _delete_zip_locked(_job)
        _job = job
    worker = threading.Thread(target=run_export_job, args=(job.id,), daemon=True)
    worker.start()
    return job


def run_export_job(job_id: str) -> None:
    job = _job_if_current(job_id)
    if not job:
        return
    zip_path = None
    try:
        _update_progress(job_id, message="正在收集回忆")
        memories = collect_memories()
        media_items = collect_media_items(memories)
        _update_progress(job_id, current=0, total=len(media_items), message="正在打包文件")

        export_dir = get_export_dir()
        folder_name = Path(job.filename).stem
        zip_path = export_dir / f"{job_id}.zip"
        failed = _write_archive(job_id, zip_path, folder_name, memories, media_items)
        stats = {
            "timeline": len(memories.get("timeline") or []),
            "moods": len(memories.get("moods") or []),
            "wishes": len(memories.get("wishes") or []),
            "capsules": len(memories.get("capsules") or []),
            "places": len(memories.get("map") or []),
            "photos": len(memories.get("photos") or []),
            "playlist": len(memories.get("playlist") or []),
            "cooking_records": len((memories.get("cooking") or {}).get("records") or []),
            "files_downloaded": memories["media"]["downloaded"],
            "files_failed": len(failed),
        }
        _finish_job(job_id, zip_path=zip_path, stats=stats)
    except Exception:
        logger.exception("回忆导出失败")
        if zip_path and zip_path.exists():
            zip_path.unlink(missing_ok=True)
        _fail_job(job_id, "打包失败，请稍后重试")


def collect_memories() -> dict:
    with get_db() as conn:
        with conn.cursor() as cursor:
            timeline = _fetch(
                cursor,
                f"SELECT id, event_date, title, content, photo_url, icon FROM `{settings.timeline_table}` ORDER BY event_date ASC, id ASC",
                ["id", "event_date", "title", "content", "photo_url", "icon"],
            )
            moods = _fetch(
                cursor,
                f"SELECT id, mood_date, emoji, note, level FROM `{settings.mood_table}` ORDER BY mood_date ASC",
                ["id", "mood_date", "emoji", "note", "level"],
            )
            wishes = _fetch(
                cursor,
                f"SELECT id, content, x, y, color, created_at FROM `{settings.wish_table}` ORDER BY created_at ASC",
                ["id", "content", "x", "y", "color", "created_at"],
            )
            capsules = _fetch(
                cursor,
                f"SELECT id, content, open_date, is_opened, created_at FROM `{settings.capsule_table}` ORDER BY open_date ASC, id ASC",
                ["id", "content", "open_date", "is_opened", "created_at"],
            )
            markers = _fetch(
                cursor,
                f"SELECT id, title, note, photo_url, lat, lng, visit_date, created_at FROM `{settings.map_table}` ORDER BY visit_date ASC, id ASC",
                ["id", "title", "note", "photo_url", "lat", "lng", "visit_date", "created_at"],
            )
            marker_photos = _fetch(
                cursor,
                f"SELECT marker_id, photo_url, sort_order FROM `{settings.map_photos_table}` ORDER BY marker_id ASC, sort_order ASC, id ASC",
                ["marker_id", "photo_url", "sort_order"],
                optional=True,
            )
            if not marker_photos:
                marker_photos = _fetch(
                    cursor,
                    f"SELECT marker_id, photo_url FROM `{settings.map_photos_table}` ORDER BY marker_id ASC, id ASC",
                    ["marker_id", "photo_url"],
                )
            photos = _fetch(
                cursor,
                "SELECT id, filename, oss_url, description, created_at FROM love_photos ORDER BY created_at ASC, id ASC",
                ["id", "filename", "oss_url", "description", "created_at"],
            )
            playlist = _fetch(
                cursor,
                f"SELECT id, song_name, artist, netease_id, platform, sort_order FROM `{settings.music_table}` ORDER BY sort_order ASC, id ASC",
                ["id", "song_name", "artist", "netease_id", "platform", "sort_order"],
            )
            cooking_records = _fetch(
                cursor,
                """
                SELECT cr.id, cr.recipe_id, r.title, cr.username, cr.cooked_date, cr.rating,
                       cr.mood, cr.photo_url, cr.note, cr.next_time_improvement
                FROM `love_cooking_records` cr
                LEFT JOIN `love_recipes` r ON r.id = cr.recipe_id
                ORDER BY cr.cooked_date ASC, cr.id ASC
                """,
                [
                    "id", "recipe_id", "title", "username", "cooked_date", "rating",
                    "mood", "photo_url", "note", "next_time_improvement",
                ],
                optional=True,
            )
            menus = _fetch(
                cursor,
                """
                SELECT id, title, menu_date, description, status, created_by
                FROM `love_cooking_menus`
                ORDER BY COALESCE(menu_date, DATE(created_at)) ASC, id ASC
                """,
                ["id", "title", "menu_date", "description", "status", "created_by"],
                optional=True,
            )
            menu_items = _fetch(
                cursor,
                """
                SELECT mi.menu_id, mi.recipe_id, r.title, mi.sort_order, mi.note
                FROM `love_cooking_menu_items` mi
                LEFT JOIN `love_recipes` r ON r.id = mi.recipe_id
                ORDER BY mi.menu_id ASC, mi.sort_order ASC, mi.id ASC
                """,
                ["menu_id", "recipe_id", "title", "sort_order", "note"],
                optional=True,
            )

    photos_by_marker: dict[int, list[str]] = {}
    for row in marker_photos:
        marker_id = row.get("marker_id")
        url = str(row.get("photo_url") or "").strip()
        if marker_id is None or not url:
            continue
        photos_by_marker.setdefault(int(marker_id), []).append(url)

    map_items = []
    for marker in markers:
        item = dict(marker)
        item["photos"] = photos_by_marker.get(int(marker["id"]), [])
        map_items.append(item)

    menus_out = []
    items_by_menu: dict[int, list[dict]] = {}
    for item in menu_items:
        menu_id = item.get("menu_id")
        if menu_id is None:
            continue
        items_by_menu.setdefault(int(menu_id), []).append(
            {
                "recipe_id": item.get("recipe_id"),
                "title": item.get("title") or "",
                "sort_order": item.get("sort_order") or 0,
                "note": item.get("note") or "",
            }
        )
    for menu in menus:
        row = dict(menu)
        row["items"] = items_by_menu.get(int(menu["id"]), [])
        menus_out.append(row)

    return {
        "version": EXPORT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "timeline": timeline,
        "moods": moods,
        "wishes": wishes,
        "capsules": capsules,
        "map": map_items,
        "photos": photos,
        "playlist": playlist,
        "cooking": {
            "records": cooking_records,
            "menus": menus_out,
        },
    }


def collect_media_items(memories: dict) -> list[dict]:
    items: list[dict] = []
    used = {"photos": set(), "map": set(), "cooking": set()}

    for photo in memories.get("photos") or []:
        filename = sanitize_upload_filename(str(photo.get("filename") or ""))
        if not filename:
            continue
        archive_name = _unique_name(used["photos"], filename)
        key = oss_object_key(str(photo.get("oss_url") or "")) or f"photos/{filename}"
        items.append(
            {
                "archive_path": f"photos/{archive_name}",
                "oss_key": key if key.startswith("photos/") else f"photos/{filename}",
                "local_path": settings.photos_dir / filename,
            }
        )
        photo["archive_path"] = f"photos/{archive_name}"

    for marker in memories.get("map") or []:
        urls = list(marker.get("photos") or [])
        cover = str(marker.get("photo_url") or "").strip()
        if cover and cover not in urls:
            urls.insert(0, cover)
        archive_paths = []
        for url in urls:
            archive_path = _map_archive_path(url, used["map"])
            if not archive_path:
                continue
            items.append(
                {
                    "archive_path": archive_path,
                    "oss_key": oss_object_key(url),
                    "local_path": None,
                }
            )
            archive_paths.append(archive_path)
        marker["archive_paths"] = archive_paths

    for record in (memories.get("cooking") or {}).get("records") or []:
        url = str(record.get("photo_url") or "").strip()
        if not url:
            continue
        key = oss_object_key(url)
        filename = sanitize_upload_filename(Path(key or url).name)
        if not filename:
            continue
        archive_name = _unique_name(used["cooking"], filename)
        archive_path = f"cooking/{archive_name}"
        local = settings.photos_dir / filename if not (key or "").startswith("map/") else None
        items.append(
            {
                "archive_path": archive_path,
                "oss_key": key,
                "local_path": local,
            }
        )
        record["archive_path"] = archive_path

    for event in memories.get("timeline") or []:
        url = str(event.get("photo_url") or "").strip()
        if not url:
            continue
        key = oss_object_key(url)
        filename = sanitize_upload_filename(Path(key or urlparse(url).path).name)
        if not filename:
            continue
        if any(item["archive_path"].endswith(f"/{filename}") for item in items):
            event["archive_path"] = next(
                item["archive_path"] for item in items if item["archive_path"].endswith(f"/{filename}")
            )
            continue
        archive_name = _unique_name(used["photos"], filename)
        archive_path = f"photos/{archive_name}"
        items.append(
            {
                "archive_path": archive_path,
                "oss_key": key,
                "local_path": settings.photos_dir / filename,
            }
        )
        event["archive_path"] = archive_path

    return items


def oss_object_key(url: str) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    path = text
    if "://" in text:
        path = unquote(urlparse(text).path or "")
    path = path.lstrip("/")
    for prefix in ("photos/", "map/"):
        idx = path.find(prefix)
        if idx >= 0:
            return path[idx:].split("?")[0]
    return None


def render_markdown(memories: dict) -> str:
    days: dict[str, dict[str, list]] = {}

    def bucket(day: str | None) -> dict[str, list]:
        key = day or "未标注日期"
        return days.setdefault(key, {"stories": [], "moods": [], "places": [], "photos": [], "wishes": [], "cooking": []})

    for item in memories.get("timeline") or []:
        bucket(_day(item.get("event_date")))["stories"].append(item)
    for item in memories.get("moods") or []:
        bucket(_day(item.get("mood_date")))["moods"].append(item)
    for item in memories.get("map") or []:
        bucket(_day(item.get("visit_date")))["places"].append(item)
    for item in memories.get("photos") or []:
        bucket(_day(item.get("created_at")))["photos"].append(item)
    for item in memories.get("wishes") or []:
        bucket(_day(item.get("created_at")))["wishes"].append(item)
    for item in (memories.get("cooking") or {}).get("records") or []:
        bucket(_day(item.get("cooked_date")))["cooking"].append(item)

    lines = [
        "# xiguasaiLove 回忆备份",
        "",
        f"导出时间：{memories.get('exported_at') or ''}",
        "",
    ]
    ordered = sorted((key for key in days if key != "未标注日期"), reverse=False)
    if "未标注日期" in days:
        ordered.append("未标注日期")

    for day in ordered:
        group = days[day]
        lines.append(f"## {day}")
        lines.append("")
        if group["moods"]:
            lines.append("### 心情")
            for item in group["moods"]:
                note = _one_line(item.get("note"))
                extra = f" {note}" if note else ""
                lines.append(f"- {item.get('emoji') or ''}{extra}".strip())
            lines.append("")
        if group["stories"]:
            lines.append("### 故事")
            for item in group["stories"]:
                title = _one_line(item.get("title")) or "未命名"
                content = _one_line(item.get("content"))
                lines.append(f"- {item.get('icon') or ''} {title}".strip())
                if content:
                    lines.append(f"  {content}")
            lines.append("")
        if group["places"]:
            lines.append("### 足迹")
            for item in group["places"]:
                title = _one_line(item.get("title")) or "未命名地点"
                note = _one_line(item.get("note"))
                lines.append(f"- {title}")
                if note:
                    lines.append(f"  {note}")
            lines.append("")
        if group["photos"]:
            lines.append("### 照片")
            for item in group["photos"]:
                name = item.get("archive_path") or item.get("filename") or ""
                desc = _one_line(item.get("description"))
                lines.append(f"- {name}{f'  {desc}' if desc else ''}".rstrip())
            lines.append("")
        if group["wishes"]:
            lines.append("### 愿望")
            for item in group["wishes"]:
                lines.append(f"- {_one_line(item.get('content'))}")
            lines.append("")
        if group["cooking"]:
            lines.append("### 做过的菜")
            for item in group["cooking"]:
                title = _one_line(item.get("title")) or "菜谱"
                note = _one_line(item.get("note"))
                lines.append(f"- {title}{f'  {note}' if note else ''}")
            lines.append("")

    capsules = memories.get("capsules") or []
    if capsules:
        lines.extend(["## 时间胶囊", ""])
        for item in capsules:
            open_date = _day(item.get("open_date")) or "未定"
            content = _one_line(item.get("content"))
            lines.append(f"- {open_date}：{content}")
        lines.append("")

    playlist = memories.get("playlist") or []
    if playlist:
        lines.extend(["## 歌单", ""])
        for item in playlist:
            lines.append(f"- {_one_line(item.get('song_name'))} — {_one_line(item.get('artist'))}")
        lines.append("")

    menus = (memories.get("cooking") or {}).get("menus") or []
    if menus:
        lines.extend(["## 菜单", ""])
        for menu in menus:
            title = _one_line(menu.get("title")) or "菜单"
            when = _day(menu.get("menu_date")) or ""
            lines.append(f"- {title}{f'（{when}）' if when else ''}")
            for item in menu.get("items") or []:
                lines.append(f"  - {_one_line(item.get('title'))}")
        lines.append("")

    failed = (memories.get("media") or {}).get("failed") or []
    if failed:
        lines.extend(["## 未能打包的文件", ""])
        for item in failed:
            lines.append(f"- {item.get('path')}: {item.get('reason')}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_readme(memories: dict) -> str:
    media = memories.get("media") or {}
    return (
        "这是 xiguasaiLove 的回忆备份，只导出数据，不能一键恢复到网站。\n\n"
        "包含：\n"
        "- memories.json  结构化数据，方便以后导入\n"
        "- memories.md    按日期整理的可读年表\n"
        "- photos/        相册原图\n"
        "- map/           足迹照片\n"
        "- cooking/       做饭记录里的成品图（如有）\n\n"
        "不含登录密码、邀请码、网易云 Cookie、OSS 密钥和大模型密钥。\n"
        "压缩包里是全部相册原图，请自己妥善保存。\n\n"
        f"导出时间：{memories.get('exported_at') or ''}\n"
        f"已打包文件：{media.get('downloaded', 0)} 张\n"
        f"失败：{len(media.get('failed') or [])} 张\n"
    )


def compress_for(name: str) -> int:
    """图片和音视频已经压过，再 DEFLATE 只会浪费 CPU，体积几乎不变。"""
    suffix = Path(name).suffix.lower()
    return zipfile.ZIP_STORED if suffix in _STORE_SUFFIXES else zipfile.ZIP_DEFLATED


def _write_archive(job_id: str, zip_path: Path, folder_name: str, memories: dict, items: list[dict]) -> list[dict]:
    if zip_path.exists():
        zip_path.unlink()
    bucket = get_oss_bucket()
    failed: list[dict] = []
    total = len(items)
    write_lock = threading.Lock()
    done = 0

    def mark_progress() -> None:
        nonlocal done
        with write_lock:
            done += 1
            current = done
        _update_progress(
            job_id,
            current=current,
            total=total,
            message=f"正在打包照片 {current}/{total}" if total else "正在打包文件",
        )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        if items:
            workers = max(1, min(MEDIA_FETCH_WORKERS, len(items)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_prepare_media, item, bucket) for item in items]
                for future in as_completed(futures):
                    item, payload = future.result()
                    archive_path = item["archive_path"]
                    if payload is None:
                        failed.append({"path": archive_path, "reason": "文件不存在或读取失败"})
                    else:
                        arcname = f"{folder_name}/{archive_path}"
                        with write_lock:
                            _add_zip_member(archive, arcname, payload)
                    mark_progress()

        memories["media"] = {
            "downloaded": len(items) - len(failed),
            "failed": failed,
        }
        _update_progress(job_id, current=total, total=total, message="正在写入目录")
        _add_zip_member(
            archive,
            f"{folder_name}/memories.json",
            json.dumps(memories, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"),
        )
        _add_zip_member(archive, f"{folder_name}/memories.md", render_markdown(memories).encode("utf-8"))
        _add_zip_member(archive, f"{folder_name}/README.txt", render_readme(memories).encode("utf-8"))
    return failed


def _add_zip_member(archive: zipfile.ZipFile, arcname: str, payload: bytes | Path) -> None:
    compress = compress_for(arcname)
    if isinstance(payload, Path):
        archive.write(payload, arcname=arcname, compress_type=compress)
        return
    info = zipfile.ZipInfo(filename=arcname)
    info.compress_type = compress
    archive.writestr(info, payload)


def _prepare_media(item: dict, bucket) -> tuple[dict, bytes | Path | None]:
    local = _local_media_path(item)
    if local is not None:
        return item, local
    return item, _read_oss_bytes(item, bucket)


def _local_media_path(item: dict) -> Path | None:
    local_path = item.get("local_path")
    if not local_path:
        return None
    path = Path(local_path)
    if path.is_file():
        return path
    return None


def _read_oss_bytes(item: dict, bucket) -> bytes | None:
    oss_key = item.get("oss_key")
    if not bucket or not oss_key:
        return None
    try:
        obj = bucket.get_object(oss_key)
        data = obj.read() if obj is not None else None
        return data or None
    except Exception:
        logger.warning("OSS 读取失败: %s", oss_key, exc_info=True)
        return None


def _fetch(cursor, sql: str, fields: list[str], optional: bool = False) -> list[dict]:
    lowered = " ".join(sql.lower().split())
    if any(hint in lowered for hint in _SECRET_TABLE_HINTS):
        raise RuntimeError("backup refused to query secret table")
    try:
        cursor.execute(sql)
        rows = cursor.fetchall() or []
    except Exception:
        if optional:
            return []
        logger.warning("备份查询失败: %s", " ".join(sql.split()), exc_info=True)
        return []
    result = []
    for row in rows:
        item = {}
        for index, field in enumerate(fields):
            item[field] = _json_default(row[index]) if index < len(row) else None
        result.append(item)
    return result


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    return text[:10]


def _one_line(value) -> str:
    return " ".join(str(value or "").split())


def _unique_name(used: set[str], filename: str) -> str:
    if filename not in used:
        used.add(filename)
        return filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while True:
        candidate = f"{stem}_{index}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _map_archive_path(url: str, used: set[str]) -> str | None:
    key = oss_object_key(url)
    filename = sanitize_upload_filename(Path(key or urlparse(url).path).name)
    if not filename:
        return None
    return f"map/{_unique_name(used, filename)}"


def _job_if_current(job_id: str) -> ExportJob | None:
    with _lock:
        if _job and _job.id == job_id:
            return _job
    return None


def _update_progress(job_id: str, current: int | None = None, total: int | None = None, message: str | None = None) -> None:
    with _lock:
        if not _job or _job.id != job_id:
            return
        if current is not None:
            _job.progress.current = current
        if total is not None:
            _job.progress.total = total
        if message is not None:
            _job.progress.message = message


def _finish_job(job_id: str, zip_path: Path, stats: dict) -> None:
    with _lock:
        if not _job or _job.id != job_id:
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)
            return
        _job.status = "done"
        _job.zip_path = zip_path
        _job.stats = stats
        _job.progress.message = "可以下载了"
        _job.expires_at = datetime.now() + EXPORT_TTL


def _fail_job(job_id: str, message: str) -> None:
    with _lock:
        if not _job or _job.id != job_id:
            return
        _job.status = "failed"
        _job.error = message
        _job.progress.message = message


def _delete_zip_locked(job: ExportJob | None) -> None:
    if job and job.zip_path and job.zip_path.exists():
        try:
            job.zip_path.unlink()
        except Exception:
            logger.warning("清理旧备份失败: %s", job.zip_path, exc_info=True)


def _expire_locked() -> None:
    global _job
    if not _job:
        return
    if _job.status == "done" and datetime.now() >= _job.expires_at:
        _delete_zip_locked(_job)
        _job = None
        return
    if _job.status == "packing" and datetime.now() - _job.created_at >= PACK_TIMEOUT:
        _job.status = "failed"
        _job.error = "导出超时，请重试"
