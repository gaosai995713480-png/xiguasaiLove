"""
高德 API 代理服务
"""
import json
import logging
import urllib.request
from urllib.parse import quote

from ..config import settings
from ..database import get_config

logger = logging.getLogger(__name__)


def resolve_gaode_key() -> str:
    """解析高德 Web 服务 Key，数据库配置优先于进程环境变量。"""
    for key in ("AMAP_KEY", "TRIPSTAR_AMAP_WEB_KEY"):
        value = str(get_config(key) or "").strip()
        if value:
            return value
    return str(settings.gaode_key or "").strip()


def proxy_gaode(url: str, params: dict, gaode_key: str) -> dict:
    """代理调用高德 API，统一添加 key。"""
    params["key"] = gaode_key
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    full_url = f"{url}?{qs}"
    try:
        req = urllib.request.Request(full_url, headers={"User-Agent": "xiguasaiLove/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("proxy_gaode error: %s", e)
        return {"status": "0", "info": str(e)}
