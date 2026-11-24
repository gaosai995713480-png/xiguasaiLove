import json
from datetime import datetime, timedelta

from backend.tripstar.task_store import TripStarTaskStore


def test_processing_task_is_recovered_as_failed_after_restart(tmp_path):
    store = TripStarTaskStore(tmp_path, stale_after_seconds=1)
    store.create("stale001", {"city": "西安"}, owner="alice")

    path = tmp_path / "stale001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updated_at"] = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    restarted = TripStarTaskStore(tmp_path, stale_after_seconds=1)
    task = restarted.get("stale001")

    assert task["status"] == "failed"
    assert task["stage"] == "stale"
    assert task["owner"] == "alice"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "failed"


def test_task_store_limits_final_task_files(tmp_path):
    store = TripStarTaskStore(tmp_path, max_task_files=2)

    for index in range(3):
        task_id = f"task{index}"
        store.create(task_id, {"city": "西安"}, owner="alice")
        store.update(
            task_id,
            status="completed",
            result={"data": {"city": "西安"}},
        )

    assert len(list(tmp_path.glob("*.json"))) == 2


def test_recent_completed_filters_by_owner(tmp_path):
    store = TripStarTaskStore(tmp_path)
    for task_id, owner in (("alice01", "alice"), ("bob0001", "bob")):
        store.create(task_id, {"city": "西安"}, owner=owner)
        store.update(task_id, status="completed", result={"data": {"city": "西安"}})

    assert [item["task_id"] for item in store.recent_completed(owner="alice")] == ["alice01"]
    assert {item["task_id"] for item in store.recent_completed(owner=None)} == {"alice01", "bob0001"}
