"""健康检查测试。"""
from __future__ import annotations

from app.config import PROJECT_ROOT


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "PhotoRestore"
    assert body["status"] == "ok"
    assert body["storage"] == "ok"
    assert body["version"] == (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_health_capabilities(client):
    caps = client.get("/api/health").json()["capabilities"]
    assert caps["llm"] is False
    assert caps["demo_mode"] is True
    assert caps["engine"] == "classic+onnx"
    assert caps["model_count"] >= 3
    assert caps["max_upload_bytes"] > 0
    assert caps["worker_concurrency"] >= 1
