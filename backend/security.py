"""轻量级的进程内限流和客户端地址解析。

当前项目没有引入 Redis，限流只作为单进程的第一道防线；
如果将来使用多 worker，应把这里替换为共享存储实现。
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

from fastapi import Request

from .config import settings


class SlidingWindowLimiter:
    """线程安全的滑动窗口限流器。"""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """记录一次访问；超过限制时返回 False。"""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(self._events) > 4096:
                stale_keys = [
                    item_key
                    for item_key, item_events in self._events.items()
                    if not item_events or item_events[-1] <= cutoff
                ]
                for item_key in stale_keys:
                    self._events.pop(item_key, None)
                events = self._events.setdefault(key, deque())
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


def get_client_ip(request: Request) -> str:
    """返回用于限流/点赞去重的客户端地址。

    只有显式开启 TRUST_PROXY_HEADERS 时才信任代理头，避免客户端
    直接伪造 X-Real-IP 绕过登录、点歌台和点赞限流。
    """
    if settings.trust_proxy_headers:
        forwarded = (request.headers.get("X-Real-IP") or "").strip()
        if not forwarded:
            forwarded = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded[:64]
    return (request.client.host if request.client and request.client.host else "unknown")[:64]


login_limiter = SlidingWindowLimiter(limit=8, window_seconds=5 * 60)
login_ip_limiter = SlidingWindowLimiter(limit=30, window_seconds=5 * 60)
registration_limiter = SlidingWindowLimiter(limit=5, window_seconds=60 * 60)
gallery_limiter = SlidingWindowLimiter(limit=10, window_seconds=5 * 60)
password_limiter = SlidingWindowLimiter(limit=8, window_seconds=5 * 60)
