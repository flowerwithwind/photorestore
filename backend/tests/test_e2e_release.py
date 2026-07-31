"""D10 发布验收端到端测试：真实 HTTP 栈（TestClient + lifespan 线程执行器/事件总线）。

覆盖发布验收完整用户链路：
- 上传（真实字节、非图片 400、超大 413、扩展名 400）→ 创建任务 → 队列 → SSE 契约
  （snapshot/update/done；快照含 task_id/task_type/status/progress/phase/
   params_hash/error/result/ts/seq；done 仅 {task_id, ts}）→ 产物下载 →
  批量入队 → 重跑 → 取消 → 画廊 GET/DELETE → 演示种子（/api/images/seed）；
- 失败场景：任务异常（模型缺失 failed、原图文件缺失 failed）、非法参数 422、
  图像不存在 404、重复入队 409。
"""
from __future__ import annotations

import base64
import io
import json
import time

from PIL import Image

from app import config
from app.models import TaskStatus
from app.storage import db

TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
SSE_FIELDS = {
    "task_id", "task_type", "status", "progress", "phase",
    "params_hash", "error", "result", "ts", "seq",
}


def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _png_bytes(width: int = 64, height: int = 48, color=(70, 110, 180)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(client, name: str = "photo.png", data: bytes | None = None):
    data = data if data is not None else _png_bytes()
    return client.post(
        "/api/images/upload",
        files={"file": (name, data, "image/png")},
    )


def _create_task(client, image_id: int, task_type: str = "restore", params: dict | None = None) -> int:
    r = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": task_type, "params": params or {}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    return body["task_id"]


def _wait_terminal(client, task_id: int) -> dict:
    _wait_until(
        lambda: client.get(f"/api/tasks/{task_id}").json()["status"] in TERMINAL
    )
    return client.get(f"/api/tasks/{task_id}").json()


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


def _assert_sse_contract(parsed: list[dict]) -> dict:
    """校验 snapshot/update/done 契约，返回首个 snapshot 的 data。"""
    events = [item["event"] for item in parsed]
    assert events[0] == "snapshot"
    assert events[-1] == "done"
    assert "update" in events
    done = parsed[-1]["data"]
    assert set(done) == {"task_id", "ts"}
    seqs: list[int] = []
    for item in parsed[:-1]:
        data = item["data"]
        assert set(data) == SSE_FIELDS
        seqs.append(int(data["seq"]))
    assert seqs == sorted(seqs)  # seq 单调递增
    return parsed[0]["data"]


def test_release_full_journey_upload_sse_download_batch_rerun_cancel_gallery_demo(client):
    # 1) 真实字节上传 → 201，登记落盘（D10 上传字节链路）
    r = _upload(client, "release-photo.png")
    assert r.status_code == 201
    image = r.json()
    image_id = image["id"]
    assert image["filename"].startswith("upload_")
    assert image["format"] == "png"
    assert image["size_bytes"] > 0
    source = config.UPLOADS_DIR / image["filename"]
    assert source.is_file()
    assert source.read_bytes().startswith(b"\x89PNG")

    # 2) 创建任务 → 队列，参数指纹非空
    task_id = _create_task(
        client, image_id, "restore", {"denoise_h": 5, "output_format": "jpeg"}
    )
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] in {"queued", "processing", "succeeded"}
    assert detail["params_hash"]

    # 3) SSE 事件流契约（snapshot/update/done + 全字段 + seq 单调 + done 精简）
    with client.stream("GET", f"/api/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = list(response.iter_lines())
    parsed = _parse_stream(lines)
    snapshot = _assert_sse_contract(parsed)
    assert snapshot["task_id"] == task_id
    assert snapshot["task_type"] == "restore"

    # 4) 终态成功 + 产物下载
    task = _wait_terminal(client, task_id)
    assert task["status"] == "succeeded"
    assert task["progress"] == 100
    outputs = task["result"]["outputs"]
    assert len(outputs) == 1
    download = client.get(f"/api/tasks/{task_id}/outputs/0/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/jpeg")
    payload = download.content
    assert payload.startswith(b"\xff\xd8") and len(payload) > 0
    out_path = config.OUTPUTS_DIR / outputs[0]["filename"]
    assert out_path.is_file()

    # 5) 画廊 GET：图片 + 任务摘要（含产物 download_url）
    gallery = client.get("/api/images").json()
    found = next(item for item in gallery["items"] if item["id"] == image_id)
    assert any(t["status"] == "succeeded" for t in found["tasks"])

    # 6) 批量入队：两张图同一参数 → 每图独立任务，全部成功
    second = _upload(client, "release-photo-2.png").json()
    r = client.post(
        "/api/tasks/batch",
        json={
            "image_ids": [image_id, second["id"]],
            "task_type": "restore",
            "params": {"output_format": "png"},
        },
    )
    assert r.status_code == 201
    batch = r.json()
    assert batch["count"] == 2
    assert len(batch["task_ids"]) == 2
    for tid in batch["task_ids"]:
        assert _wait_terminal(client, tid)["status"] == "succeeded"

    # 7) 重跑：终态任务 → 新 task_id + 相同 params_hash（同图多版本）
    first_batch = batch["task_ids"][0]
    r = client.post(f"/api/tasks/{first_batch}/rerun")
    assert r.status_code == 200
    rerun = r.json()
    assert rerun["source_task_id"] == first_batch
    assert rerun["task_id"] != first_batch
    assert rerun["params_hash"] == client.get(f"/api/tasks/{first_batch}").json()["params_hash"]
    assert _wait_terminal(client, rerun["task_id"])["status"] == "succeeded"

    # 8) 取消：大图 + deblur 制造 processing 窗口 → cancelled 终态
    big = _upload(client, "release-big.png", _png_bytes(1600, 1200)).json()
    long_task = _create_task(client, big["id"], "restore", {"deblur": True})
    _wait_until(
        lambda: client.get(f"/api/tasks/{long_task}").json()["status"] == "processing"
    )
    r = client.post(f"/api/tasks/{long_task}/cancel")
    assert r.status_code == 200
    task = _wait_terminal(client, long_task)
    assert task["status"] == "cancelled"
    assert task["error"] is None

    # 9) 画廊 DELETE：级联删除图片与其任务
    r = client.delete(f"/api/images/{image_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert client.get(f"/api/images/{image_id}").status_code == 404
    gallery = client.get("/api/images").json()
    assert all(item["id"] != image_id for item in gallery["items"])

    # 10) 演示模式：seed 端点（前端演示图走 /api/images/seed）→ 可下载
    demo = base64.b64encode(_png_bytes(24, 18)).decode("ascii")
    r = client.post("/api/images/seed", json={"filename": "demo-x.png", "data_base64": demo})
    assert r.status_code == 201
    seed = r.json()
    assert seed["filename"].startswith("seed_")
    dl = client.get(f"/api/images/{seed['id']}/download")
    assert dl.status_code == 200
    assert dl.content.startswith(b"\x89PNG")


def test_release_failure_paths_upload_validation_model_missing_422_404_409(client):
    # 非图片内容 → 400 invalid_image（内容校验）
    r = _upload(client, "fake.png", b"this is not an image at all")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_image"

    # 扩展名不允许 → 400 unsupported_format
    r = _upload(client, "notes.txt", b"hello")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_format"

    # 超大字节 → 413 image_too_large，且不残留任何文件
    before = {p.name for p in config.UPLOADS_DIR.iterdir()}
    huge = b"\x89PNG\r\n\x1a\n" + b"\0" * (config.MAX_UPLOAD_BYTES + 1)
    r = _upload(client, "huge.png", huge)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "image_too_large"
    after = {p.name for p in config.UPLOADS_DIR.iterdir()}
    assert after == before

    # 合法图片 → 后续失败场景复用
    image = _upload(client, "ok.png").json()
    image_id = image["id"]

    # 非法参数 → 422 invalid_params
    r = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {"denoise_h": 999}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_params"

    # 图像不存在 → 404 image_not_found
    r = client.post(
        "/api/tasks",
        json={"image_ids": [999999], "task_type": "restore", "params": {}},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "image_not_found"

    # 模型缺失 → 任务 failed（测试模型目录为空，upscale 依赖 realesrgan onnx）
    up_task = _create_task(client, image_id, "upscale", {"scale": 2})
    task = _wait_terminal(client, up_task)
    assert task["status"] == "failed"
    assert "模型文件缺失" in task["error"]

    # 原图文件缺失 → 任务 failed（回归 D10 修复的上传字节链路：仅登记无字节必失败）
    ghost_id = db.create_image(
        filename="ghost.png",
        size_bytes=10,
        format_="png",
        path=str(config.UPLOADS_DIR / "ghost-nowhere.png"),
    )
    ghost_task = _create_task(client, ghost_id, "restore", {})
    task = _wait_terminal(client, ghost_task)
    assert task["status"] == "failed"
    assert "原图文件缺失" in task["error"]

    # 重复入队 → 409（非终态任务重跑 task_not_terminal）
    queued_id = db.create_task(
        task_type="restore",
        status=TaskStatus.QUEUED,
        params={},
        params_hash="e2e-dup-hash",
        image_ids=[image_id],
    )
    r = client.post(f"/api/tasks/{queued_id}/rerun")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "task_not_terminal"