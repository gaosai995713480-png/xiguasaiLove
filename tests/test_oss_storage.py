"""OSS 照片排他上传的单元测试。"""
from backend.services import oss_storage


class FakeBucket:
    def __init__(self, conflict=False):
        self.conflict = conflict
        self.calls = []

    def put_object(self, key, data, headers=None):
        self.calls.append((key, data, headers))
        if self.conflict:
            error = RuntimeError("object exists")
            error.status = 409
            error.code = "FileAlreadyExists"
            raise error


def test_exclusive_upload_sends_forbid_overwrite_header(monkeypatch):
    bucket = FakeBucket()
    monkeypatch.setattr(oss_storage, "get_oss_bucket", lambda: bucket)

    result = oss_storage.upload_to_oss_exclusive("photo.jpg", b"data")

    assert result == "ok"
    assert bucket.calls == [
        (
            "photos/photo.jpg",
            b"data",
            {"x-oss-forbid-overwrite": "true"},
        )
    ]


def test_exclusive_upload_reports_existing_object(monkeypatch):
    bucket = FakeBucket(conflict=True)
    monkeypatch.setattr(oss_storage, "get_oss_bucket", lambda: bucket)

    assert oss_storage.upload_to_oss_exclusive("photo.jpg", b"data") == "exists"
