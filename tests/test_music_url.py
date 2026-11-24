import secrets
import time

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.routers.music import playback_proxy_url, resolve_meting_url, to_https_media_url
from backend.routers import music
from backend.main import app
from fastapi.testclient import TestClient


def _authed_client() -> TestClient:
    client = TestClient(app)
    token = secrets.token_urlsafe(24)
    _cache_session(token, UserInfo(username="music_test_user", role="visitor"), time.time() + 3600)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return client


def test_to_https_media_url_upgrades_http():
    assert (
        to_https_media_url("http://m701.music.126.net/song.mp3")
        == "https://m701.music.126.net/song.mp3"
    )


def test_to_https_media_url_keeps_https_and_empty():
    assert to_https_media_url("https://m701.music.126.net/song.mp3").startswith("https://")
    assert to_https_media_url("") == ""
    assert to_https_media_url("/api/music/bgm/file/a.mp3") == "/api/music/bgm/file/a.mp3"


def test_resolve_meting_url_upgrades_netease_http(monkeypatch):
    music._url_cache.clear()
    monkeypatch.setattr(
        music,
        "call_meting",
        lambda *args, **kwargs: {
            "ok": True,
            "data": {"url": "http://m701.music.126.net/abc.mp3"},
        },
    )

    assert resolve_meting_url("2067368745", "netease") == "https://m701.music.126.net/abc.mp3"


def test_resolve_meting_url_empty_does_not_use_outer_fallback(monkeypatch):
    music._url_cache.clear()
    monkeypatch.setattr(
        music,
        "call_meting",
        lambda *args, **kwargs: {"ok": True, "data": {"url": ""}},
    )
    assert resolve_meting_url("435288399", "netease") == ""
    assert "music.163.com/song/media/outer" not in (resolve_meting_url("435288399", "netease") or "")


def test_music_url_returns_same_origin_stream(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://m701.music.126.net/abc.mp3",
    )
    data = _authed_client().get("/api/music/url?id=435288399&platform=netease").json()
    assert data == {"url": playback_proxy_url("435288399", "netease")}


def test_music_validation_errors_use_real_http_status():
    client = _authed_client()

    url_response = client.get("/api/music/url")
    search_response = client.get("/api/music/search")
    add_response = client.post("/api/music", json={})
    delete_response = client.delete("/api/music?id=0")

    assert url_response.status_code == 400
    assert search_response.status_code == 400
    assert add_response.status_code == 400
    assert delete_response.status_code == 400


def test_music_public_endpoints_require_login():
    anonymous = TestClient(app)
    assert anonymous.get("/api/music").status_code == 401
    assert anonymous.get("/api/music/search?keyword=test").status_code == 401
    assert anonymous.get("/api/music/url?id=1").status_code == 401
    assert anonymous.get("/api/music/stream?id=1").status_code == 401
    assert anonymous.get("/api/music/lyric?id=1").status_code == 401


def test_url_cache_is_bounded(monkeypatch):
    music._url_cache.clear()
    monkeypatch.setattr(music, "call_meting", lambda *args, **kwargs: {"ok": True, "data": {"url": ""}})
    monkeypatch.setattr(music.logger, "warning", lambda *args, **kwargs: None)

    for index in range(music._URL_CACHE_MAX_ENTRIES + 50):
        resolve_meting_url(str(index), "netease")

    assert len(music._url_cache) <= music._URL_CACHE_MAX_ENTRIES


class _FakeAudio:
    def __init__(self, status=206, chunks=None, content_type="audio/mpeg", extra=None):
        self.status_code = status
        self.chunks = list(chunks or [b"ID3x"])
        self.headers = {"content-type": content_type, **(extra or {})}
        self.closed = False

    async def aiter_raw(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class _FakeClient:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


def test_music_stream_proxies_audio(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://m701.music.126.net/abc.mp3",
    )
    async def fake_open(url, headers):
        return _FakeClient(), _FakeAudio(
            chunks=[b"ID", b"3x"],
            extra={"content-range": "bytes 0-3/100", "content-length": "4"},
        )

    monkeypatch.setattr(music, "_open_audio_upstream", fake_open)
    response = _authed_client().get(
        "/api/music/stream?id=435288399&platform=netease",
        headers={"Range": "bytes=0-3"},
    )
    assert response.status_code == 206
    assert response.content == b"ID3x"
    assert response.headers["content-type"].startswith("audio/mpeg")


def test_music_stream_rejects_html(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://music.163.com/404",
    )
    async def fake_open(url, headers):
        return _FakeClient(), _FakeAudio(status=200, chunks=[b"<html>"], content_type="text/html")

    monkeypatch.setattr(music, "_open_audio_upstream", fake_open)
    response = _authed_client().get("/api/music/stream?id=435288399&platform=netease")
    assert response.status_code == 502


def test_music_stream_rejects_oversized_upstream(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://m701.music.126.net/abc.mp3",
    )

    async def fake_open(url, headers):
        return _FakeClient(), _FakeAudio(
            status=200,
            chunks=[b"too large"],
            extra={"content-length": str(music._MAX_AUDIO_STREAM_BYTES + 1)},
        )

    monkeypatch.setattr(music, "_open_audio_upstream", fake_open)
    response = _authed_client().get("/api/music/stream?id=1&platform=netease")

    assert response.status_code == 413


def test_music_stream_maps_upstream_timeout_to_502(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://m701.music.126.net/abc.mp3",
    )

    async def fake_open(url, headers):
        raise music.httpx.ReadTimeout("upstream timeout")

    monkeypatch.setattr(music, "_open_audio_upstream", fake_open)
    response = _authed_client().get("/api/music/stream?id=1&platform=netease")

    assert response.status_code == 502
