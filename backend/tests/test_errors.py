"""统一错误响应测试。"""
from __future__ import annotations


def test_404_returns_unified_shape(client):
    r = client.get("/api/not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]


def test_settings_roundtrip(client):
    from app.storage import db

    db.set_setting("k", {"a": 1})
    assert db.get_setting("k") == {"a": 1}
    assert db.get_setting("missing", "d") == "d"
