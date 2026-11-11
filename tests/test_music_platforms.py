from fastapi.testclient import TestClient

from backend.main import app
from backend.services.meting import MUSIC_PLATFORMS


client = TestClient(app)


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
