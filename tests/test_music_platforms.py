import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend.dependencies import SESSION_COOKIE_NAME, UserInfo, _cache_session
from backend.main import app
from backend.services.meting import MUSIC_PLATFORMS


client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_client():
    token = secrets.token_urlsafe(24)
    _cache_session(
        token,
        UserInfo(username="music_platform_user", role="visitor"),
        time.time() + 3600,
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)
    yield
    client.cookies.clear()


def test_music_write_platforms_only_netease():
    assert MUSIC_PLATFORMS == {"netease"}


def test_search_rejects_removed_platform():
    response = client.get(
        "/api/music/search",
        params={"keyword": "test", "platform": "tencent"},
    )

    assert response.status_code == 400
    assert "网易云" in response.json()["error"]


def test_jukebox_rejects_removed_platform():
    response = client.post(
        "/api/jukebox",
        json={
            "song_id": "1",
            "song_name": "test",
            "artist": "test",
            "platform": "kugou",
        },
    )

    assert response.status_code == 400
    assert "网易云" in response.json()["error"]
