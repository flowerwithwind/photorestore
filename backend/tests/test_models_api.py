"""模型元数据接口 + 设置/清理一致性测试（hermetic：临时 MODELS_DIR / DATA_DIR，D8）。"""
from __future__ import annotations

import pytest

from app import config
from app.storage import db


@pytest.fixture(autouse=True)
def clean_models_dir():
    """每个用例前清空 models/ 目录，保证就绪状态断言可重复。"""
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for child in config.MODELS_DIR.iterdir():
        if child.is_file():
            child.unlink()
    yield


def _write_model(name: str, size: int = 1024) -> None:
    config.MODELS_DIR.joinpath(name).write_bytes(b"x" * size)


def _wipe_uploads() -> None:
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    for child in config.UPLOADS_DIR.iterdir():
        if child.is_file():
            child.unlink()


def test_models_api_reports_missing_when_empty(client):
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["models_dir"] == str(config.MODELS_DIR)
    assert body["summary"] == {"total": 3, "ready": 0, "missing": 3, "total_bytes": 0}

    by_key = {item["key"]: item for item in body["items"]}
    assert set(by_key) == {"restore", "upscale", "colorize"}
    upscale = by_key["upscale"]
    assert upscale["ready"] is False
    assert upscale["required"] is True
    assert upscale["missing"] == ["realesrgan-x2.onnx", "realesrgan-x4.onnx"]
    assert [f["name"] for f in upscale["files"]] == ["realesrgan-x2.onnx", "realesrgan-x4.onnx"]
    assert all(f["exists"] is False and f["size_bytes"] == 0 for f in upscale["files"])
    assert upscale["total_bytes"] == 0
    assert "download_models.py" in upscale["download_hint"]
    assert "--only upscale" in upscale["download_hint"]


def test_models_api_reports_ready_and_size(client):
    _write_model("realesrgan-x4.onnx", 2048)
    _write_model("ddcolor.onnx", 4096)

    body = client.get("/api/models").json()
    by_key = {item["key"]: item for item in body["items"]}

    restore = by_key["restore"]
    assert restore["ready"] is True
    assert restore["missing"] == []
    assert restore["total_bytes"] == 2048
    assert restore["required"] is False

    upscale = by_key["upscale"]
    assert upscale["ready"] is False
    assert upscale["missing"] == ["realesrgan-x2.onnx"]
    x4 = {f["name"]: f for f in upscale["files"]}["realesrgan-x4.onnx"]
    assert x4["exists"] is True and x4["size_bytes"] == 2048

    colorize = by_key["colorize"]
    assert colorize["ready"] is True
    assert colorize["total_bytes"] == 4096

    assert body["summary"]["ready"] == 2
    assert body["summary"]["missing"] == 1
    assert body["summary"]["total_bytes"] == 2048 + 4096


def test_models_api_lists_extra_files(client):
    _write_model("realesrgan-x4.onnx")
    _write_model("stray.bin", 64)
    body = client.get("/api/models").json()
    assert {"name": "stray.bin", "size_bytes": 64} in body["extra_files"]


def test_settings_concurrency_defaults_to_env(client):
    body = client.get("/api/settings").json()
    assert body["worker_concurrency"] >= 1
    assert body["source"] in {"env", "db"}
    assert body["max_upload_bytes"] > 0


def test_settings_concurrency_save_and_read(client):
    r = client.post("/api/settings", json={"worker_concurrency": 4})
    assert r.status_code == 200
    saved = r.json()
    assert saved["saved"] is True
    assert saved["worker_concurrency"] == 4
    assert "重启" in saved["note"]

    body = client.get("/api/settings").json()
    assert body["worker_concurrency"] == 4
    assert body["source"] == "db"
    assert body["persisted"] == 4
    # settings 表已持久化
    assert db.get_setting("worker_concurrency") == 4


def test_settings_concurrency_rejects_out_of_range(client):
    assert client.post("/api/settings", json={"worker_concurrency": 0}).status_code == 422
    assert client.post("/api/settings", json={"worker_concurrency": 99}).status_code == 422
    assert client.post("/api/settings", json={"worker_concurrency": "x"}).status_code == 422


def test_cleanup_and_stats_consistent(client):
    """一键清理后占用统计应归零：统计 -> dry_run -> 实际清理 -> 统计一致。"""
    _wipe_uploads()
    upload = config.UPLOADS_DIR / "a.jpg"
    output = config.OUTPUTS_DIR / "b.png"
    upload.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    upload.write_bytes(b"u" * 100)
    output.write_bytes(b"o" * 200)

    before = client.get("/api/storage/stats").json()
    assert before["uploads"] == {"count": 1, "bytes": 100}
    assert before["outputs"] == {"count": 1, "bytes": 200}
    assert before["total"] == {"count": 2, "bytes": 300}

    # dry_run 只计算不删除
    dry = client.post(
        "/api/storage/cleanup",
        json={"scope": "all", "max_count": 0, "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["count"] == 2
    assert dry.json()["freed_bytes"] == 300
    assert upload.exists() and output.exists()

    # 实际清理
    r = client.post(
        "/api/storage/cleanup",
        json={"scope": "all", "max_count": 0, "dry_run": False},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2
    assert r.json()["freed_bytes"] == 300
    assert not upload.exists() and not output.exists()

    after = client.get("/api/storage/stats").json()
    assert after["total"] == {"count": 0, "bytes": 0}
