"""TripStar 本地任务状态存储。"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


FINAL_STATUSES = {"completed", "failed"}
DEFAULT_STALE_AFTER_SECONDS = 45 * 60
DEFAULT_RETENTION_SECONDS = 30 * 24 * 60 * 60
DEFAULT_MAX_TASK_FILES = 500
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class TripStarTaskStore:
    """内存 + JSON 文件的轻量任务存储。

    任务状态只允许从 processing 进入 completed/failed 终态，避免前端轮询永远等不到结果。
    """

    def __init__(
        self,
        task_dir: Path,
        *,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_task_files: int = DEFAULT_MAX_TASK_FILES,
    ):
        self.task_dir = task_dir
        self.stale_after_seconds = max(1, int(stale_after_seconds))
        self.retention_seconds = max(1, int(retention_seconds))
        self.max_task_files = max(1, int(max_task_files))
        self._tasks: dict[str, dict[str, Any]] = {}
        self._file_mtimes: dict[str, int] = {}
        self._lock = threading.RLock()

    def ready(self) -> bool:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        return self.task_dir.exists()

    def create(
        self,
        task_id: str,
        request_payload: dict[str, Any],
        owner: str = "",
    ) -> dict[str, Any]:
        if not _TASK_ID_RE.fullmatch(str(task_id or "")):
            raise ValueError("invalid task id")
        task = {
            "task_id": task_id,
            "plan_id": task_id,
            "owner": owner,
            "status": "processing",
            "stage": "submitted",
            "progress": 5,
            "message": "任务已提交，正在初始化旅行智能体...",
            "request_payload": request_payload,
            "result": None,
            "error": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._tasks[task_id] = task
            self._persist(task_id, task)
            self._cleanup_locked()
        return task.copy()

    def get(self, task_id: str) -> dict[str, Any] | None:
        if not _TASK_ID_RE.fullmatch(str(task_id or "")):
            return None
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                try:
                    disk_mtime = self._task_path(task_id).stat().st_mtime_ns
                except OSError:
                    disk_mtime = 0
                if disk_mtime > self._file_mtimes.get(task_id, 0):
                    loaded = self._load(task_id)
                    if loaded is not None:
                        task = loaded
                task = self._mark_if_stale(task_id, task)
                self._tasks[task_id] = task
                return task.copy()

            loaded = self._load(task_id)
            if loaded is None:
                return None
            self._tasks[task_id] = loaded
            return loaded.copy()

    def update(
        self,
        task_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        if not _TASK_ID_RE.fullmatch(str(task_id or "")):
            return None
        with self._lock:
            task = self._tasks.get(task_id) or self._load(task_id)
            if task is None:
                return None

            current_status = task.get("status", "processing")
            if current_status in FINAL_STATUSES:
                return task.copy()

            if status is not None:
                task["status"] = status
            if stage is not None:
                task["stage"] = stage
            if progress is not None:
                task["progress"] = max(0, min(100, int(progress)))
            if message is not None:
                task["message"] = message
            if result is not None:
                task["result"] = result
            if error is not None:
                task["error"] = error

            if task.get("status") in FINAL_STATUSES:
                task["progress"] = 100
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")

            self._tasks[task_id] = task
            self._persist(task_id, task)
            return task.copy()

    def recent_completed(self, limit: int = 10, owner: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_locked()
        items: list[dict[str, Any]] = []
        paths = sorted(
            self.task_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("status") != "completed":
                continue
            if owner is not None and payload.get("owner") != owner:
                continue
            result_data = ((payload.get("result") or {}).get("data") or {})
            request_payload = payload.get("request_payload") or {}
            items.append(
                {
                    "task_id": payload.get("task_id") or path.stem,
                    "plan_id": payload.get("plan_id") or path.stem,
                    "owner": payload.get("owner") or "",
                    "city": result_data.get("city") or request_payload.get("city") or "",
                    "start_date": result_data.get("start_date") or request_payload.get("start_date") or "",
                    "end_date": result_data.get("end_date") or request_payload.get("end_date") or "",
                    "travel_days": result_data.get("travel_days") or request_payload.get("travel_days") or 0,
                    "updated_at": payload.get("updated_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
            if len(items) >= limit:
                break
        return items

    def _task_path(self, task_id: str) -> Path:
        return self.task_dir / f"{task_id}.json"

    def _persist(self, task_id: str, task: dict[str, Any]) -> None:
        if not _TASK_ID_RE.fullmatch(str(task_id or "")):
            raise ValueError("invalid task id")
        self.task_dir.mkdir(parents=True, exist_ok=True)
        target = self._task_path(task_id)
        tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.json.tmp")
        tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        self._file_mtimes[task_id] = target.stat().st_mtime_ns

    def _load(self, task_id: str) -> dict[str, Any] | None:
        if not _TASK_ID_RE.fullmatch(str(task_id or "")):
            return None
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            self._file_mtimes[task_id] = path.stat().st_mtime_ns
        except OSError:
            pass
        if task.get("status") not in FINAL_STATUSES and task.get("status") != "processing":
            task["status"] = "failed"
            task["stage"] = "failed"
            task["progress"] = 100
            task["message"] = "任务状态异常，请重新生成。"
            task["error"] = task["message"]
            self._persist(task_id, task)
        task = self._mark_if_stale(task_id, task)
        return task

    def _mark_if_stale(self, task_id: str, task: dict[str, Any]) -> dict[str, Any]:
        if task.get("status") != "processing":
            return task
        updated_at = self._parse_timestamp(task.get("updated_at") or task.get("created_at"))
        if updated_at is None:
            try:
                updated_at = datetime.fromtimestamp(self._task_path(task_id).stat().st_mtime)
            except OSError:
                return task
        if datetime.now() - updated_at <= timedelta(seconds=self.stale_after_seconds):
            return task

        task["status"] = "failed"
        task["stage"] = "stale"
        task["progress"] = 100
        task["message"] = "任务长时间没有进展，已标记失败，请重新提交。"
        task["error"] = task["message"]
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._persist(task_id, task)
        return task

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def _cleanup_locked(self) -> None:
        """清理过期终态任务，并限制任务文件总量。调用方必须已持有锁。"""
        self.task_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        retention_cutoff = now.timestamp() - self.retention_seconds
        stale_temp_cutoff = now.timestamp() - max(self.stale_after_seconds, 3600)

        for path in self.task_dir.glob("*.json.tmp"):
            try:
                if path.stat().st_mtime < stale_temp_cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

        final_paths: list[Path] = []
        for path in self.task_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if mtime < retention_cutoff:
                    path.unlink(missing_ok=True)
                    self._tasks.pop(path.stem, None)
                    self._file_mtimes.pop(path.stem, None)
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("status") in FINAL_STATUSES:
                final_paths.append(path)

        all_paths = list(self.task_dir.glob("*.json"))
        overflow = len(all_paths) - self.max_task_files
        if overflow <= 0:
            return

        for path in sorted(final_paths, key=lambda item: item.stat().st_mtime):
            if overflow <= 0:
                break
            try:
                path.unlink(missing_ok=True)
                self._tasks.pop(path.stem, None)
                self._file_mtimes.pop(path.stem, None)
                overflow -= 1
            except OSError:
                continue
