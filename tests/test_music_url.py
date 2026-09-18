from backend.routers.music import resolve_meting_url, to_https_media_url


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
    from backend.routers import music

    monkeypatch.setattr(
        music,
        "call_meting",
        lambda *args, **kwargs: {
            "ok": True,
            "data": {"url": "http://m701.music.126.net/abc.mp3"},
        },
    )

    assert resolve_meting_url("2067368745", "netease") == "https://m701.music.126.net/abc.mp3"
