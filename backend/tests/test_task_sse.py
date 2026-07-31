"""SSE 进度推送测试：事件流格式（snapshot/update/done）、终态立即 done、断开不影响执行、404。"""
from __future__ import annotations

import io
import json
import time

from PIL import Image

from app import config


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _create_image(client, name: str = "sse.png", width: int = 16, height: int = 12) -> int:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (60, 90, 160)).save(buffer, format="PNG")
    data = buffer.getvalue()
    path = config.UPLOADS_DIR / name
    path.write_bytes(data)
    r = client.post(
        "/api/images",
        json={
            "filename": name,
            "size_bytes": len(data),
            "format": "png",
            "path": str(path),
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def _create_task(client, image_id: int) -> int:
    r = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {}},
    )
    assert r.status_code == 201
    return r.json()["task_id"]


def _parse_stream(lines: list[str]) -> list[dict]:
    parsed: list[dict] = []
    current: dict | None = None
    for line in lines:
        if line.startswith("event: "):
            current = {"event": line[7:], "data": None}
            parsed.append(current)
        elif line.startswith("data: ") and current is not None:
            current["data"] = json.loads(line[6:])
    return parsed


def test_sse_event_stream_snapshot_update_done(client):
    image_id = _create_image(client)
    task_id = _create_task(client, image_id)

    with client.stream("GET", f"/api/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = list(response.iter_lines())

    parsed = _parse_stream(lines)
    events = [item["event"] for item in parsed]
    assert events[0] == "snapshot"
    assert events[-1] == "done"
    assert "update" in events

    snapshot = parsed[0]["data"]
    assert snapshot["task_id"] == task_id
    assert snapshot["status"] in {"queued", "processing", "succeeded"}

    # snapshot/update 快照都包含 D5 前端需要的字段（done 仅 task_id + ts）
    for item in parsed:
        if item["event"] in {"snapshot", "update"}:
            for key in ("task_id", "task_type", "status", "progress", "phase",
                        "params_hash", "error", "result", "ts", "seq"):
                assert key in item["data"]
            assert isinstance(item["data"]["seq"], int)

    updates = [item["data"] for item in parsed if item["event"] == "update"]
    statuses = [item["status"] for item in updates]
    assert "processing" in statuses
    assert "succeeded" in statuses
    last_update = updates[-1]
    assert last_update["status"] == "succeeded"
    assert last_update["progress"] == 100
    assert last_update["phase"] == "save"

    # seq 契约：snapshot 携带当前最新 seq（可能为 0），update 单调递增
    seqs = [snapshot["seq"], *[u["seq"] for u in updates]]
    assert all(isinstance(s, int) and s >= 0 for s in seqs)
    assert seqs == sorted(seqs)
    assert seqs[-1] >= len(updates)

    done = parsed[-1]["data"]
    assert done["task_id"] == task_id
    assert done["ts"]
    assert set(done.keys()) == {"task_id", "ts"}  # done 仅 task_id + ts


def test_sse_finished_task_immediate_done(client):
    image_id = _create_image(client)
    task_id = _create_task(client, image_id)
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")

    with client.stream("GET", f"/api/tasks/{task_id}/events") as response:
        lines = list(response.iter_lines())

    parsed = _parse_stream(lines)
    assert parsed[0]["event"] == "snapshot"
    assert parsed[0]["data"]["status"] == "succeeded"
    assert parsed[-1]["event"] == "done"
    assert parsed[-1]["data"]["task_id"] == task_id
    assert any(item["event"] == "update" for item in parsed)


def test_sse_disconnect_does_not_abort_task(client):
    image_id = _create_image(client)
    task_id = _create_task(client, image_id)

    with client.stream("GET", f"/api/tasks/{task_id}/events") as response:
        for line in response.iter_lines():
            if line.startswith("event: update"):
                break  # 收到第一条 update 后主动断开

    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded")
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    assert task["phase"] == "save"


def test_sse_task_not_found(client):
    r = client.get("/api/tasks/99999/events")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "task_not_found"
