"""取消行为测试：queued 直接取消；processing 检查点中断（executor cancel 事件）；API 两态。"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime
import pytest
from PIL import Image

from app import config
from app.models import TaskStatus
from app.services import tasks as tasks_svc
from app.services.executor import TaskCancelledError, TaskExecutor
from app.services.model_registry import default_registry
from app.storage import db


@pytest.fixture()
def db_ready():
    db.init_db()
    db.wipe_data()
    yield


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


class CheckpointHandler:
    """阻塞在检查点前的处理器：release 后调用 progress.check_cancel()。"""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.interrupted = False

    def run(self, task_id, image_ids, params, progress):
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("handler 未在预期时间内被释放")
        try:
            progress.check_cancel()
        except TaskCancelledError:
            self.interrupted = True
            raise
        progress.update(100, "save")
        return {"ok": True}


def _make_image() -> int:
    return db.create_image(filename="a.png", size_bytes=10, format_="png", path="/tmp/a.png")


def _make_task() -> int:
    return tasks_svc.create_task([_make_image()], "restore", {})


def test_cancel_processing_checkpoint(db_ready):
    """processing：executor.cancel 事件 + DB 状态，处理链在检查点中断并保持 cancelled。"""
    handler = CheckpointHandler()
    executor = TaskExecutor(concurrency=1, handler=handler)
    executor.start()
    try:
        task_id = _make_task()
        executor.enqueue(task_id)
        assert handler.started.wait(timeout=2)
        assert db.get_task(task_id)["status"] == TaskStatus.PROCESSING

        result = tasks_svc.cancel_task(task_id, executor=executor)
        assert result["status"] == TaskStatus.CANCELLED

        handler.release.set()
        _wait_until(lambda: handler.interrupted)
        task = db.get_task(task_id)
        assert task["status"] == TaskStatus.CANCELLED
        assert task["error"] is None
        assert task["finished_at"]
    finally:
        handler.release.set()
        executor.stop()


class BlockingUpscaleSession:
    """慢速假 ONNX 会话：推理 sleep 2s，占满 concurrency=1 的 worker。"""

    def __init__(self, path, providers=None):
        self.path = Path(str(path))

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        time.sleep(2.0)
        arr = input_feed["input"]
        return [
            np.zeros((1, 3, arr.shape[2] * 2, arr.shape[3] * 2), dtype=np.float32)
        ]


class SlowUpscaleSession:
    """慢速假 ONNX 会话：推理中 sleep，给取消留出窗口。"""

    def __init__(self, path, providers=None):
        self.path = Path(str(path))

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        time.sleep(0.4)
        arr = input_feed["input"]
        return [
            np.zeros((1, 3, arr.shape[2] * 2, arr.shape[3] * 2), dtype=np.float32)
        ]


def test_cancel_processing_via_api(client, monkeypatch):
    """API：processing 中取消成功，推理返回后清理，任务保持 cancelled、无半成品。"""
    monkeypatch.setattr(onnxruntime, "InferenceSession", SlowUpscaleSession)
    default_registry.clear_cache()
    models_dir = config.MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "realesrgan-x2.onnx").write_bytes(b"fake-onnx")

    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(buffer, format="PNG")
    data = buffer.getvalue()
    path = config.UPLOADS_DIR / "cancel.png"
    path.write_bytes(data)
    image_id = client.post(
        "/api/images",
        json={
            "filename": "cancel.png",
            "size_bytes": len(data),
            "format": "png",
            "path": str(path),
        },
    ).json()["id"]
    task_id = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "upscale", "params": {"scale": 2}},
    ).json()["task_id"]

    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] == "processing")
    r = client.post(f"/api/tasks/{task_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    time.sleep(0.7)  # 等推理线程返回并完成清理
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "cancelled"
    assert task["error"] is None
    leftovers = [
        p.name
        for p in config.OUTPUTS_DIR.iterdir()
        if p.name.endswith(f"_t{task_id}.jpeg") or p.name.endswith(f"_t{task_id}.png")
    ]
    assert leftovers == []
    assert not list(config.TMP_DIR.iterdir())
    default_registry.clear_cache()


def test_cancel_queued_via_api(client, monkeypatch):
    """API：queued 直接取消（用慢推理任务占满 concurrency=1 的 worker，
    保证目标任务在取消时仍停留在 queued，避免与执行器拾起竞态）。"""
    monkeypatch.setattr(onnxruntime, "InferenceSession", BlockingUpscaleSession)
    default_registry.clear_cache()
    models_dir = config.MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "realesrgan-x2.onnx").write_bytes(b"fake-onnx")

    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(buffer, format="PNG")
    data = buffer.getvalue()
    blocker_path = config.UPLOADS_DIR / "blocker.png"
    blocker_path.write_bytes(data)
    blocker_image_id = client.post(
        "/api/images",
        json={
            "filename": "blocker.png",
            "size_bytes": len(data),
            "format": "png",
            "path": str(blocker_path),
        },
    ).json()["id"]
    blocker_task_id = client.post(
        "/api/tasks",
        json={
            "image_ids": [blocker_image_id],
            "task_type": "upscale",
            "params": {"scale": 2},
        },
    ).json()["task_id"]
    _wait_until(
        lambda: client.get(f"/api/tasks/{blocker_task_id}").json()["status"] == "processing"
    )

    image_id = client.post(
        "/api/images",
        json={"filename": "q.png", "size_bytes": 10, "format": "png"},
    ).json()["id"]
    task_id = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {}},
    ).json()["task_id"]
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "queued"

    r = client.post(f"/api/tasks/{task_id}/cancel")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["finished_at"]
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "cancelled"
    default_registry.clear_cache()
