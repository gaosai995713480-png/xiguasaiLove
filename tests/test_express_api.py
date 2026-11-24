"""
快递查询接口回归测试
"""
import os
import secrets
import sys
import time
import unittest

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.main import app
from backend.dependencies import (
    SESSION_COOKIE_NAME,
    UserInfo,
    _sessions,
    _cache_session,
)


client = TestClient(app)


class ExpressApiTestCase(unittest.TestCase):
    def setUp(self):
        client.cookies.clear()
        _sessions.clear()

    def login_as_admin(self):
        token = secrets.token_urlsafe(16)
        _cache_session(
            token,
            UserInfo(username="admin_user", role="admin"),
            time.time() + 3600,
        )
        client.cookies.set(SESSION_COOKIE_NAME, token)

    def test_update_config_rejects_none_value_without_server_error(self):
        self.login_as_admin()

        response = client.post("/api/express/config", json={"customer": None})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "updated": 0})

    def test_update_config_rejects_non_string_value_without_server_error(self):
        self.login_as_admin()

        response = client.post("/api/express/config", json={"key": 123456})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "updated": 0})


if __name__ == "__main__":
    unittest.main()
