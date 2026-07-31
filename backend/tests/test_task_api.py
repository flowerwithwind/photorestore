"""任务 API 测试：入队即返回、详情进度/阶段/时间线、产物下载、错误响应（hermetic）。"""
from __future__ import annotations

import io
import time

from PIL import Image

from app import config

_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _create_image(
    client,
    name: str = "photo.png",
    size: int | None = None,
    fmt: str = "png",
    width: int = 16,
    height: int = 12,
) -> int:
    """写一张真实图片文件并登记 images 记录（D4 真实处理器需要真实原图）。"""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (80, 120, 200)).save(buffer, format=_FORMATS[fmt])
    data = buffer.getvalue()
    path = config.UPLOADS_DIR / name
    path.write_bytes(data)
    r = client.post(
        "/api/images",
        json={
            "filename": name,
            "size_bytes": size if size is not None else len(data),
            "format": fmt,
            "path": str(path),
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_post_task_returns_queued_and_detail(client):
    image_id = _create_image(client)
    r = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {"scale": 2}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    task_id = body["task_id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] in {"queued", "processing", "succeeded"}
    assert detail["progress"] >= 0
    assert detail["phase"] in {"decode", "preprocess", "infer", "postprocess", "save", None}

    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert detail["phase"] == "save"
    assert detail["params"] == {"scale": 2}
    assert len(detail["params_hash"]) == 64
    assert detail["image_ids"] == [image_id]
    assert detail["created_at"] and detail["started_at"] and detail["finished_at"]

    # D4：结果含模型名、产物信息与下载 URL；详情含阶段时间线
    result = detail["result"]
    assert result["model"] == "classic-restore"
    assert result["task_type"] == "restore"
    output = result["outputs"][0]
    assert output["image_id"] == image_id
    assert output["format"] == "jpeg"
    assert output["width"] == 16 and output["height"] == 12
    assert output["size_bytes"] > 0
    assert output["input_size_bytes"] > 0
    assert output["download_url"] == f"/api/tasks/{task_id}/outputs/0/download"
    assert output["path"]

    logs = detail["phase_logs"]
    assert [log["phase"] for log in logs] == [
        "decode",
        "preprocess",
        "infer",
        "postprocess",
        "save",
    ]
    assert all(log["started_at"] and log["finished_at"] and log["duration_ms"] >= 0 for log in logs)


def test_post_task_missing_image_404(client):
    r = client.post(
        "/api/tasks",
        json={"image_ids": [999], "task_type": "restore", "params": {}},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "image_not_found"


def test_get_task_404(client):
    r = client.get("/api/tasks/12345")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "task_not_found"


def test_list_tasks(client):
    image_id = _create_image(client)
    task_ids = []
    for _ in range(2):
        r = client.post(
            "/api/tasks",
            json={"image_ids": [image_id], "task_type": "restore", "params": {}},
        )
        task_ids.append(r.json()["task_id"])
    _wait_until(
        lambda: all(
            client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded"
            for task_id in task_ids
        )
    )
    items = client.get("/api/tasks").json()["items"]
    assert {item["id"] for item in items} >= set(task_ids)
    assert all("progress" in item and "phase" in item for item in items)


def test_image_registration_and_get(client):
    image_id = _create_image(client, name="old.png", size=2048, fmt="png")
    image = client.get(f"/api/images/{image_id}").json()
    assert image["filename"] == "old.png"
    assert image["size_bytes"] == 2048
    assert image["format"] == "png"
    assert image["path"]


def test_image_unsupported_format(client):
    r = client.post("/api/images", json={"filename": "a.gif", "size_bytes": 1, "format": "gif"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_format"


def test_download_output(client):
    image_id = _create_image(client)
    task_id = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {"output_format": "png"}},
    ).json()["task_id"]
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    detail = client.get(f"/api/tasks/{task_id}").json()
    output = detail["result"]["outputs"][0]

    r = client.get(output["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content.startswith(b"\x89PNG")
    assert len(r.content) == output["size_bytes"]


def test_download_output_404(client):
    image_id = _create_image(client)
    task_id = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {}},
    ).json()["task_id"]
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    r = client.get(f"/api/tasks/{task_id}/outputs/9/download")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "output_not_found"
