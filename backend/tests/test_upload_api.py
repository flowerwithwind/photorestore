"""D10 真实字节上传端点测试：multipart /api/images/upload 校验与落盘（hermetic）。"""
from __future__ import annotations

import io
import time

from PIL import Image

from app import config


def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _png_bytes(width: int = 32, height: int = 24, color=(60, 90, 160)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(client, data: bytes, filename: str = "photo.png", content_type: str = "image/png"):
    return client.post(
        "/api/images/upload",
        files={"file": (filename, data, content_type)},
    )


def test_upload_png_registers_file_and_task_succeeds(client):
    data = _png_bytes()
    r = _upload(client, data)
    assert r.status_code == 201
    body = r.json()
    assert body["format"] == "png"
    assert body["size_bytes"] > 0
    assert body["path"].startswith(str(config.UPLOADS_DIR))
    stored = config.UPLOADS_DIR / body["filename"]
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"\x89PNG")

    # 上传登记后即可创建任务并成功处理（真实字节链路闭环）
    task = client.post(
        "/api/tasks",
        json={"image_ids": [body["id"]], "task_type": "restore", "params": {}},
    )
    assert task.status_code == 201
    task_id = task.json()["task_id"]
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "succeeded"
    assert detail["result"]["outputs"][0]["image_id"] == body["id"]


def test_upload_jpeg_normalized_and_gallery_listable(client):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buffer, format="JPEG")
    data = buffer.getvalue()
    r = _upload(client, data, filename="scan.jpg")
    assert r.status_code == 201
    body = r.json()
    assert body["format"] == "jpeg"
    assert client.get(f"/api/images/{body['id']}/download").status_code == 200
    listed = client.get("/api/images").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == body["id"]


def test_upload_large_dimension_downscaled_by_pipeline(client):
    # 大图（长边 9000 > MAX_IMAGE_DIMENSION=8000）：上传接受，管线等比缩放
    data = _png_bytes(width=9000, height=12)
    r = _upload(client, data, filename="wide.png")
    assert r.status_code == 201
    image_id = r.json()["id"]
    task = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {}},
    )
    task_id = task.json()["task_id"]
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    output = client.get(f"/api/tasks/{task_id}").json()["result"]["outputs"][0]
    assert output["input_width"] == 9000  # 原始尺寸被记录
    assert output["width"] <= 8000  # 处理时等比缩放


def test_upload_non_image_rejected_400(client):
    r = _upload(client, b"definitely not an image", filename="fake.png")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_image"


def test_upload_oversized_rejected_413(client):
    data = b"x" * (config.MAX_UPLOAD_BYTES + 1)
    r = _upload(client, data, filename="huge.png")
    assert r.status_code == 413
    body = r.json()["error"]
    assert body["code"] == "image_too_large"
    assert body["details"]["max_bytes"] == config.MAX_UPLOAD_BYTES
    assert client.get("/api/images").json()["total"] == 0  # 无残留


def test_upload_unsupported_extension_rejected(client):
    r = _upload(client, b"x", filename="notes.txt")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_format"


def test_upload_empty_file_rejected(client):
    r = _upload(client, b"", filename="empty.png")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "empty_image"
