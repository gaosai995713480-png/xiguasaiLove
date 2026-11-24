"""照片路由"""
import io
import logging
import threading
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from ..config import settings
from ..dependencies import require_gallery_access, require_role
from ..utils import is_image_filename, sanitize_upload_filename, photo_sort_key, aligned_expires
from ..services.oss_storage import upload_to_oss_exclusive, get_oss_bucket, get_oss_domain
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["photos"])

MAX_PHOTO_BYTES = 50 * 1024 * 1024
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ZIP_SINGLE_FILE_BYTES = 50 * 1024 * 1024
MAX_PHOTO_NAME_LENGTH = 255

_PHOTO_WRITE_LOCK = threading.Lock()


class _PhotoStorageError(RuntimeError):
    pass


class _ZipReadError(Exception):
    pass


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="上传文件过大")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid content-length")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(status_code=413, detail="上传文件过大")
        body.extend(chunk)
    return bytes(body)


def _numbered_filename(filename: str, index: int) -> str | None:
    path = Path(filename)
    suffix = path.suffix
    token = f"_{index}" if index > 1 else ""
    max_stem_length = MAX_PHOTO_NAME_LENGTH - len(token) - len(suffix)
    if max_stem_length < 1:
        return None
    candidate = f"{path.stem[:max_stem_length]}{token}{suffix}"
    return candidate if is_image_filename(candidate) else None


def _name_key(filename: str) -> str:
    return filename.casefold()


def _load_photo_names(cursor) -> set[str]:
    cursor.execute("SELECT filename FROM love_photos")
    return {_name_key(row[0]) for row in (cursor.fetchall() or []) if row and row[0]}


def _reserve_oss_name(
    bucket,
    original_name: str,
    file_data: bytes,
    reserved: set[str],
    existing: set[str],
) -> str:
    for index in range(1, 10001):
        candidate = _numbered_filename(original_name, index)
        if not candidate:
            continue
        key = _name_key(candidate)
        if key in reserved or key in existing:
            continue
        result = upload_to_oss_exclusive(candidate, file_data)
        if result == "ok":
            reserved.add(key)
            return candidate
        if result == "exists":
            existing.add(key)
            continue
        raise _PhotoStorageError("failed to upload to OSS")
    raise _PhotoStorageError("too many files with the same name")


def _reserve_local_name(
    photos_dir: Path,
    original_name: str,
    reserved: set[str],
) -> str:
    for index in range(1, 10001):
        candidate = _numbered_filename(original_name, index)
        if not candidate:
            continue
        key = _name_key(candidate)
        if key in reserved or (photos_dir / candidate).exists():
            continue
        reserved.add(key)
        return candidate
    raise _PhotoStorageError("too many files with the same name")


def _cleanup_new_media(bucket, object_keys: list[str], local_paths: list[Path]) -> None:
    for key in object_keys:
        try:
            bucket.delete_object(key)
        except Exception:
            logger.warning("清理本次上传的 OSS 对象失败: %s", key, exc_info=True)
    for path in local_paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.warning("清理本次写入的本地照片失败: %s", path, exc_info=True)


def _validate_zip_manifest(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise HTTPException(status_code=413, detail="ZIP 条目过多")
    total_size = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise HTTPException(status_code=400, detail="不支持加密 ZIP")
        if info.file_size > MAX_ZIP_SINGLE_FILE_BYTES:
            raise HTTPException(status_code=413, detail="ZIP 单文件过大")
        total_size += max(0, info.file_size)
        if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise HTTPException(status_code=413, detail="ZIP 解压总量过大")
    return infos


def _read_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        return archive.read(info)
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise _ZipReadError("cannot read zip entry") from exc

@router.get("/photos.json")
def list_photos(_=Depends(require_gallery_access)):
    # 彻底元数据化：优先查询数据库中的结构化对象
    bucket = get_oss_bucket()
    expires = aligned_expires()
    try:
        with get_db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, filename, oss_url, description, created_at FROM love_photos")
                rows = cursor.fetchall()
                if rows:
                    def _get_url(f_name, raw_url, is_thumb=False):
                        if bucket:
                            params = {'x-oss-process': 'image/resize,w_500,m_lfit'} if is_thumb else None
                            return bucket.sign_url('GET', f"photos/{f_name}", expires, slash_safe=True, params=params)
                        return raw_url

                    # 对查出来的数据行使用原生排序函数确保顺序 100% 对齐旧版相册
                    sorted_rows = sorted(rows, key=lambda r: photo_sort_key(Path(r[1])))

                    return [
                        {
                            "id": r[0],
                            "filename": r[1],
                            "url": _get_url(r[1], r[2], is_thumb=False),
                            "thumbnail_url": _get_url(r[1], r[2], is_thumb=True),
                            "description": r[3] if r[3] else "",
                            "created_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else ""
                        }
                        for r in sorted_rows
                    ]
    except Exception as e:
        logger.error(f"Database query failed: {e}")

    # 降级：如果数据库没有数据，则寻找本地遗留
    photos_dir = settings.photos_dir
    images = []
    if photos_dir.exists():
        for item in photos_dir.iterdir():
            if item.is_file() and is_image_filename(item.name):
                images.append(item)
    images.sort(key=photo_sort_key)
    # 必须仍然返回对象格式，以兼容前端新改造
    return [
        {
            "id": i,
            "filename": item.name,
            "url": f"photos/{quote(item.name)}",
            "description": "",
            "created_at": ""
        } 
        for i, item in enumerate(images)
    ]


@router.get("/photos/{file_name:path}")
def get_photo(file_name: str, _=Depends(require_gallery_access)):
    safe_name = sanitize_upload_filename(unquote(file_name))
    if not safe_name or not is_image_filename(safe_name):
        return JSONResponse({"error": "invalid photo name"}, status_code=400)

    target = settings.photos_dir / safe_name
    if not target.exists() or not target.is_file():
        return JSONResponse({"error": "photo not found"}, status_code=404)

    return FileResponse(target)


@router.post("/photos/upload-file")
async def upload_photo(request: Request, _=Depends(require_role("admin"))):
    file_name = request.headers.get("X-File-Name", "").strip()
    file_name = unquote(file_name)
    safe_name = sanitize_upload_filename(file_name)

    if not safe_name or not is_image_filename(safe_name):
        return JSONResponse({"error": "invalid file name"}, status_code=400)

    file_data = await _read_limited_body(request, MAX_PHOTO_BYTES)
    if not file_data:
        return JSONResponse({"error": "empty file"}, status_code=400)

    bucket = get_oss_bucket()
    if bucket:
        with _PHOTO_WRITE_LOCK:
            object_key = ""
            try:
                with get_db() as conn:
                    with conn.cursor() as cursor:
                        existing = _load_photo_names(cursor)
                        actual_name = _reserve_oss_name(
                            bucket,
                            safe_name,
                            file_data,
                            set(),
                            existing,
                        )
                        object_key = f"photos/{actual_name}"
                        oss_url = f"{get_oss_domain()}/photos/{actual_name}"
                        cursor.execute(
                            "INSERT INTO love_photos (filename, oss_url) VALUES (%s, %s)",
                            (actual_name, oss_url),
                        )
                    conn.commit()
            except _PhotoStorageError as exc:
                logger.error("照片上传失败: %s", exc)
                if object_key:
                    _cleanup_new_media(bucket, [object_key], [])
                return JSONResponse({"error": "failed to upload to OSS"}, status_code=500)
            except Exception:
                logger.exception("照片入库失败")
                if object_key:
                    _cleanup_new_media(bucket, [object_key], [])
                return JSONResponse({"error": "数据库写入失败"}, status_code=500)
        return {
            "ok": True,
            "saved": 1,
            "name": actual_name,
            "renamed": actual_name != safe_name,
        }

    photos_dir = settings.photos_dir
    photos_dir.mkdir(parents=True, exist_ok=True)
    with _PHOTO_WRITE_LOCK:
        target = None
        try:
            actual_name = _reserve_local_name(photos_dir, safe_name, set())
            target = photos_dir / actual_name
            target.write_bytes(file_data)
        except _PhotoStorageError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        except Exception:
            if target is not None:
                target.unlink(missing_ok=True)
            logger.exception("本地照片写入失败")
            return JSONResponse({"error": "照片写入失败"}, status_code=500)
    return {
        "ok": True,
        "saved": 1,
        "name": actual_name,
        "renamed": actual_name != safe_name,
    }


@router.post("/photos/import")
async def import_photos(request: Request, _=Depends(require_role("admin"))):
    archive_data = await _read_limited_body(request, MAX_ZIP_BYTES)
    if not archive_data:
        return JSONResponse({"error": "empty upload"}, status_code=400)

    photos_dir = settings.photos_dir
    bucket = get_oss_bucket()
    has_oss = bool(bucket)
    if not has_oss:
        photos_dir.mkdir(parents=True, exist_ok=True)

    domain = get_oss_domain() if has_oss else ""
    uploaded_keys: list[str] = []
    created_paths: list[Path] = []

    try:
        skipped = 0
        saved_names: list[str] = []
        with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
            infos = _validate_zip_manifest(archive)
            if has_oss:
                with _PHOTO_WRITE_LOCK:
                    with get_db() as conn:
                        with conn.cursor() as cursor:
                            existing = _load_photo_names(cursor)
                            reserved: set[str] = set()
                            total_read = 0
                            for info in infos:
                                if info.is_dir():
                                    continue
                                safe_name = sanitize_upload_filename(info.filename)
                                if not safe_name or not is_image_filename(safe_name):
                                    skipped += 1
                                    continue

                                file_data = _read_zip_member(archive, info)
                                total_read += len(file_data)
                                if len(file_data) > MAX_ZIP_SINGLE_FILE_BYTES:
                                    raise HTTPException(status_code=413, detail="ZIP 单文件过大")
                                if total_read > MAX_ZIP_UNCOMPRESSED_BYTES:
                                    raise HTTPException(status_code=413, detail="ZIP 解压总量过大")

                                actual_name = _reserve_oss_name(
                                    bucket,
                                    safe_name,
                                    file_data,
                                    reserved,
                                    existing,
                                )
                                uploaded_keys.append(f"photos/{actual_name}")
                                oss_url = f"{domain}/photos/{actual_name}"
                                cursor.execute(
                                    "INSERT INTO love_photos (filename, oss_url) VALUES (%s, %s)",
                                    (actual_name, oss_url),
                                )
                                saved_names.append(actual_name)
                        conn.commit()
            else:
                with _PHOTO_WRITE_LOCK:
                    reserved: set[str] = set()
                    total_read = 0
                    for info in infos:
                        if info.is_dir():
                            continue
                        safe_name = sanitize_upload_filename(info.filename)
                        if not safe_name or not is_image_filename(safe_name):
                            skipped += 1
                            continue

                        file_data = _read_zip_member(archive, info)
                        total_read += len(file_data)
                        if len(file_data) > MAX_ZIP_SINGLE_FILE_BYTES:
                            raise HTTPException(status_code=413, detail="ZIP 单文件过大")
                        if total_read > MAX_ZIP_UNCOMPRESSED_BYTES:
                            raise HTTPException(status_code=413, detail="ZIP 解压总量过大")

                        actual_name = _reserve_local_name(photos_dir, safe_name, reserved)
                        target = photos_dir / actual_name
                        target.write_bytes(file_data)
                        created_paths.append(target)
                        saved_names.append(actual_name)

        return {
            "ok": True,
            "saved": len(saved_names),
            "skipped": skipped,
            "names": saved_names,
        }
    except HTTPException:
        _cleanup_new_media(bucket, uploaded_keys, created_paths)
        raise
    except zipfile.BadZipFile:
        _cleanup_new_media(bucket, uploaded_keys, created_paths)
        return JSONResponse({"error": "invalid zip file"}, status_code=400)
    except _PhotoStorageError as exc:
        logger.error("照片导入上传失败: %s", exc)
        _cleanup_new_media(bucket, uploaded_keys, created_paths)
        return JSONResponse({"error": "failed to upload to OSS"}, status_code=500)
    except _ZipReadError as exc:
        logger.warning("ZIP 条目无法读取: %s", exc)
        _cleanup_new_media(bucket, uploaded_keys, created_paths)
        return JSONResponse({"error": "cannot read zip entry"}, status_code=400)
    except Exception:
        logger.exception("照片导入失败")
        _cleanup_new_media(bucket, uploaded_keys, created_paths)
        return JSONResponse({"error": "照片导入失败"}, status_code=500)


@router.delete("/photos/{file_name:path}")
def delete_photo(file_name: str, _=Depends(require_role("admin"))):
    raw_name = unquote(file_name)
    safe_name = sanitize_upload_filename(raw_name)
    if not safe_name or not is_image_filename(safe_name) or raw_name != safe_name:
        return JSONResponse({"error": "invalid photo name"}, status_code=400)

    deleted = False

    # 1. 尝试清理 OSS 及 MySQL 记录
    bucket = get_oss_bucket()
    if bucket:
        try:
            bucket.delete_object(f"photos/{safe_name}")
            with get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM love_photos WHERE filename = %s", (safe_name,))
                conn.commit()
            deleted = True
        except Exception as e:
            logger.error(f"Delete from OSS/DB failed: {e}")

    # 2. 尝试清理本地硬盘遗留（不管怎样都删一下，防漏网）
    target = settings.photos_dir / safe_name
    if target.exists() and target.is_file():
        try:
            target.unlink()
            deleted = True
        except Exception:
            pass

    if deleted:
        return {"ok": True, "deleted": safe_name}
    return JSONResponse({"error": "photo not found"}, status_code=404)
