"""任务 API 测试：入队即返回、详情进度/阶段、错误响应（hermetic：StubTaskHandler）。"""
from __future__ import annotations

import time


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _create_image(client, name: str = "photo.jpg", size: int = 1024, fmt: str = "jpg") -> int:
    r = client.post(
        "/api/images",
        json={"filename": name, "size_bytes": size, "format": fmt},
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
    assert detail["result"]["ok"] is True


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