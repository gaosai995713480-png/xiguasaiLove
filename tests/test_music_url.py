from backend.routers.music import playback_proxy_url, resolve_meting_url, to_https_media_url
from backend.routers import music
from backend.main import app
from fastapi.testclient import TestClient


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
    data = TestClient(app).get("/api/music/url?id=435288399&platform=netease").json()
    assert data == {"url": playback_proxy_url("435288399", "netease")}


class _FakeAudio:
    def __init__(self, status=206, content=b"ID3x", content_type="audio/mpeg", extra=None):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": content_type, **(extra or {})}


def test_music_stream_proxies_audio(monkeypatch):
    monkeypatch.setattr(
        music,
        "resolve_meting_url",
        lambda song_id, platform: "https://m701.music.126.net/abc.mp3",
    )
    monkeypatch.setattr(
        music.httpx,
        "get",
        lambda *args, **kwargs: _FakeAudio(
            extra={"content-range": "bytes 0-3/100", "content-length": "4"}
        ),
    )
    response = TestClient(app).get(
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
    monkeypatch.setattr(
        music.httpx,
        "get",
        lambda *args, **kwargs: _FakeAudio(status=200, content=b"<html>", content_type="text/html"),
    )
    response = TestClient(app).get("/api/music/stream?id=435288399&platform=netease")
    assert response.status_code == 502
