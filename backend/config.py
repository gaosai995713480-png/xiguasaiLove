"""
应用配置管理 - 从环境变量加载
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()

@dataclass
class Settings:
    host: str = os.getenv("LOVE_HOST", "127.0.0.1")
    port: int = int(os.getenv("LOVE_PORT", "0"))

    # Web 安全
    # 留空时只接受同源请求；多个来源用逗号分隔。
    cors_origins: str = os.getenv("CORS_ORIGINS", "")
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", str(30 * 24 * 3600)))
    trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }

    # 首次建库时使用的初始凭据。未配置时生成随机值并写入服务日志。
    initial_admin_username: str = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    initial_admin_password: str = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    initial_gallery_password: str = os.getenv("INITIAL_GALLERY_PASSWORD", "")
    initial_invite_code: str = os.getenv("INITIAL_INVITE_CODE", "")

    # MySQL
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "root")
    db_name: str = os.getenv("DB_NAME", "love_page")

    # 表名
    danmu_table: str = os.getenv("TABLE_DANMU", "love_danmu")

    timeline_table: str = os.getenv("TABLE_TIMELINE", "love_timeline")
    capsule_table: str = os.getenv("TABLE_CAPSULE", "love_capsule")
    mood_table: str = os.getenv("TABLE_MOOD", "love_mood")
    wish_table: str = os.getenv("TABLE_WISH", "love_wish")
    map_table: str = os.getenv("TABLE_MAP", "love_map")
    map_photos_table: str = os.getenv("TABLE_MAP_PHOTOS", "love_map_photos")
    music_table: str = os.getenv("TABLE_MUSIC", "love_music")
    song_request_table: str = os.getenv("TABLE_SONG_REQUEST", "love_song_requests")

    # 弹幕
    danmu_limit: int = 50
    danmu_maxlen: int = 40


    # 页面密码表
    page_password_table: str = os.getenv("TABLE_PAGE_PASSWORD", "love_page_password")

    # 用户表
    users_table: str = os.getenv("TABLE_USERS", "love_users")
    sessions_table: str = os.getenv("TABLE_SESSIONS", "love_sessions")

    # 高德 Web 服务 Key；另外兼容 TripStar 的 TRIPSTAR_AMAP_WEB_KEY。
    gaode_key: str = (
        os.getenv("AMAP_KEY", "").strip()
        or os.getenv("TRIPSTAR_AMAP_WEB_KEY", "").strip()
    )

    # 路径
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def web_dir(self) -> Path:
        return self.base_dir / "docs"

    @property
    def photos_dir(self) -> Path:
        return self.web_dir / "photos"

    @property
    def music_dir(self) -> Path:
        """本地音频目录（未配置 OSS 时的降级存储）"""
        return self.web_dir / "music"


settings = Settings()
