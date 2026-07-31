"""D7 批量与重跑测试：参数校验 / 批量原子性 / 重跑版本隔离（hermetic）。"""
from __future__ import annotations

import io
import time

from PIL import Image

from app import config
from app.models import TaskStatus
from app.storage import db


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _create_image(client, name: str, fmt: str = "png", width: int = 16, height: int = 12) -> int:
    """登记一张真实图片文件（D4 真实处理器需要真实原图）。"""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (60, 90, 160)).save(
        buffer, format="PNG" if fmt == "png" else "JPEG"
    )
    data = buffer.getvalue()
    path = config.UPLOADS_DIR / name
    path.write_bytes(data)
    r = client.post(
        "/api/images",
        json={"filename": name, "size_bytes": len(data), "format": fmt, "path": str(path)},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _task_count(client) -> int:
    return len(client.get("/api/tasks").json()["items"])


# ---------------------------------------------------------------------------
# 批量入队：POST /api/tasks/batch
# ---------------------------------------------------------------------------


def test_batch_creates_one_task_per_image_and_succeeds(client):
    image_ids = [_create_image(client, name=f"batch-{i}.png") for i in range(3)]
    r = client.post(
        "/api/tasks/batch",
        json={
            "image_ids": image_ids,
            "task_type": "restore",
            "params": {"denoise_h": 5, "output_format": "png"},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["count"] == 3
    assert body["status"] == "queued"
    task_ids = body["task_ids"]
    assert len(task_ids) == 3 and len(set(task_ids)) == 3

    for task_id, image_id in zip(task_ids, image_ids):
        detail = client.get(f"/api/tasks/{task_id}").json()
        assert detail["image_ids"] == [image_id]
        assert detail["params"] == {"denoise_h": 5, "output_format": "png"}
        assert len(detail["params_hash"]) == 64

    _wait_until(
        lambda: all(
            client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded"
            for task_id in task_ids
        )
    )
    hashes = {client.get(f"/api/tasks/{task_id}").json()["params_hash"] for task_id in task_ids}
    assert len(hashes) == 1  # 同参数 → 同 params_hash


def test_batch_invalid_params_rejected_without_residue(client):
    image_ids = [_create_image(client, name=f"bad-{i}.png") for i in range(2)]
    before = _task_count(client)
    r = client.post(
        "/api/tasks/batch",
        json={"image_ids": image_ids, "task_type": "upscale", "params": {"scale": 3}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_params"
    assert _task_count(client) == before  # 参数非法：整体失败，无残留


def test_batch_bad_output_format_rejected(client):
    image_id = _create_image(client, name="fmt.png")
    r = client.post(
        "/api/tasks/batch",
        json={"image_ids": [image_id], "task_type": "restore", "params": {"output_format": "heic"}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_params"
    assert _task_count(client) == 0


def test_batch_missing_image_rolls_back_everything(client):
    image_ids = [_create_image(client, name="ok.png")]
    image_ids.append(999999)  # 第 N 个失败
    before = _task_count(client)
    r = client.post(
        "/api/tasks/batch",
        json={"image_ids": image_ids, "task_type": "restore", "params": {}},
    )
    assert r.status_code == 404
    body = r.json()["error"]
    assert body["code"] == "image_not_found"
    assert body["details"]["image_ids"] == [999999]
    assert _task_count(client) == before  # 原子性：全量校验失败，零残留


def test_batch_dedupes_duplicate_image_ids(client):
    image_id = _create_image(client, name="dup.png")
    r = client.post(
        "/api/tasks/batch",
        json={"image_ids": [image_id, image_id], "task_type": "restore", "params": {}},
    )
    assert r.status_code == 201
    task_ids = r.json()["task_ids"]
    assert len(task_ids) == 1  # 重复 id 去重，仅创建一个任务


def test_batch_empty_image_ids_422(client):
    r = client.post(
        "/api/tasks/batch",
        json={"image_ids": [], "task_type": "restore", "params": {}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# 任务重跑：POST /api/tasks/{id}/rerun
# ---------------------------------------------------------------------------


def test_rerun_new_task_same_hash_outputs_isolated(client):
    image_id = _create_image(client, name="rerun.png")
    first = client.post(
        "/api/tasks",
        json={
            "image_ids": [image_id],
            "task_type": "restore",
            "params": {"denoise_h": 5, "output_format": "png"},
        },
    ).json()["task_id"]
    _wait_until(lambda: client.get(f"/api/tasks/{first}").json()["status"] == "succeeded")
    first_detail = client.get(f"/api/tasks/{first}").json()
    first_output = first_detail["result"]["outputs"][0]
    first_file = config.OUTPUTS_DIR / first_output["filename"]
    assert first_file.is_file()

    r = client.post(f"/api/tasks/{first}/rerun")
    assert r.status_code == 200
    body = r.json()
    assert body["source_task_id"] == first
    assert body["status"] == "queued"
    second = body["task_id"]
    assert second != first
    # 同参数 → 同 params_hash（版本隔离靠新 task_id，而非 hash 变化）
    assert body["params_hash"] == first_detail["params_hash"]

    _wait_until(lambda: client.get(f"/api/tasks/{second}").json()["status"] == "succeeded")
    second_detail = client.get(f"/api/tasks/{second}").json()
    assert second_detail["params"] == first_detail["params"]
    assert second_detail["image_ids"] == first_detail["image_ids"]
    second_output = second_detail["result"]["outputs"][0]

    # 新 task_id + 同 params_hash：产物文件名含 task_id，旧产物不被覆盖
    assert second_output["filename"] != first_output["filename"]
    assert first_file.is_file()  # 旧产物仍在
    second_file = config.OUTPUTS_DIR / second_output["filename"]
    assert second_file.is_file()  # 新产物已落盘
    assert first_output["download_url"] != second_output["download_url"]
    assert client.get(first_output["download_url"]).status_code == 200  # 旧下载仍可用


def test_rerun_non_terminal_409(client):
    image_id = _create_image(client, name="active.png")
    # 直接落库一个 queued 任务（不入队），确保重跑时处于非终态
    task_id = db.create_task(
        task_type="restore",
        status=TaskStatus.QUEUED,
        params={},
        params_hash="0" * 64,
        image_ids=[image_id],
    )
    r = client.post(f"/api/tasks/{task_id}/rerun")
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "task_not_terminal"
    assert body["details"]["status"] == "queued"


def test_rerun_missing_task_404(client):
    r = client.post("/api/tasks/123456/rerun")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "task_not_found"
