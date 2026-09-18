"""管理员回忆备份导出"""
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from ..dependencies import require_role
from ..services import backup as backup_service

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


@router.post("/export")
def start_export(_=Depends(require_role("admin"))):
    job = backup_service.start_export()
    return job.public_dict()


@router.get("/export")
def export_status(_=Depends(require_role("admin"))):
    job = backup_service.current_job()
    if not job:
        return {"status": "idle"}
    return job.public_dict()


@router.get("/export/download")
def download_export(_=Depends(require_role("admin"))):
    job = backup_service.current_job()
    if not job or job.status != "done" or not job.zip_path or not job.zip_path.is_file():
        return _error("还没有可下载的备份", 404)
    ascii_name = job.filename.encode("ascii", "ignore").decode("ascii") or "xiguasai-memory.zip"
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(job.filename)}"
        )
    }
    return FileResponse(
        job.zip_path,
        media_type="application/zip",
        headers=headers,
        filename=job.filename,
    )
