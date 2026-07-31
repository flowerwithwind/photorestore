"""D4 管线处理器端到端测试：全链路（Mock 模型）、阶段日志、失败清理、同图多版本（hermetic）。"""
from __future__ import annotations

import io
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
from app.services.executor import PHASES, TaskExecutor
from app.services.model_registry import ModelRegistry
from app.services.pipeline_handler import PipelineTaskHandler
from app.storage import db

TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}


@pytest.fixture()
def db_ready():
    db.init_db()
    db.wipe_data()
    yield


def _png_bytes(width: int = 16, height: int = 12) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (80, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_image(path: Path, width: int = 16, height: int = 12) -> int:
    data = _png_bytes(width, height)
    path.write_bytes(data)
    return db.create_image(
        filename=path.name, size_bytes=len(data), format_="png", path=str(path)
    )


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _run_task(task_id: int, registry: ModelRegistry) -> dict:
    executor = TaskExecutor(concurrency=1, handler=PipelineTaskHandler(registry=registry))
    executor.start()
    try:
        executor.enqueue(task_id)
        _wait_until(lambda: db.get_task(task_id)["status"] in TERMINAL)
    finally:
        executor.stop()
    return db.get_task(task_id)


def test_full_flow_success_and_phase_logs(db_ready, tmp_path):
    registry = ModelRegistry(models_dir=tmp_path / "models")
    image_id = _make_image(tmp_path / "input.png")
    task_id = tasks_svc.create_task([image_id], "restore", {"deblur": False})

    task = _run_task(task_id, registry)

    assert task["status"] == TaskStatus.SUCCEEDED
    assert task["progress"] == 100
    assert task["phase"] == "save"
    result = task["result"]
    assert result["model"] == "classic-restore"
    assert result["task_type"] == "restore"
    output = result["outputs"][0]
    assert output["image_id"] == image_id
    assert output["format"] == "jpeg"
    assert (output["width"], output["height"]) == (16, 12)
    assert output["size_bytes"] > 0
    assert output["input_size_bytes"] > 0
    assert output["input_width"] == 16
    assert output["download_url"] == f"/api/tasks/{task_id}/outputs/0/download"
    assert Path(output["path"]).is_file()

    # 阶段时间线：五段齐全、有起止时间与耗时
    logs = db.get_phase_logs(task_id)
    assert [log["phase"] for log in logs] == list(PHASES)
    assert all(log["started_at"] and log["finished_at"] for log in logs)
    assert all(log["duration_ms"] is not None and log["duration_ms"] >= 0 for log in logs)


class FakeUpscaleSession:
    """假 ONNX 会话：超分返回 scale 倍尺寸的全零张量。"""

    def __init__(self, path, providers=None):
        self.path = Path(str(path))

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        arr = input_feed["input"]
        scale = int(self.path.stem.rsplit("x", 1)[1])
        return [
            np.zeros((1, 3, arr.shape[2] * scale, arr.shape[3] * scale), dtype=np.float32)
        ]


def test_upscale_mock_model_end_to_end(db_ready, tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeUpscaleSession)
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "realesrgan-x2.onnx").write_bytes(b"fake-onnx")
    registry = ModelRegistry(models_dir=models_dir)
    image_id = _make_image(tmp_path / "input.png", width=8, height=6)
    task_id = tasks_svc.create_task([image_id], "upscale", {"scale": 2})

    task = _run_task(task_id, registry)

    assert task["status"] == TaskStatus.SUCCEEDED
    output = task["result"]["outputs"][0]
    assert (output["width"], output["height"]) == (16, 12)
    assert output["model"] == "realesrgan"
    assert output["input_width"] == 8


def test_missing_model_fails_with_hint(db_ready, tmp_path):
    registry = ModelRegistry(models_dir=tmp_path / "models")
    image_id = _make_image(tmp_path / "input.png")
    task_id = tasks_svc.create_task([image_id], "upscale", {"scale": 2})
    before = {p.name for p in config.OUTPUTS_DIR.iterdir()}

    task = _run_task(task_id, registry)

    assert task["status"] == TaskStatus.FAILED
    assert "download_models.py" in task["error"]
    assert task["finished_at"]
    after = {p.name for p in config.OUTPUTS_DIR.iterdir()}
    assert after == before  # 缺模型不产生任何半成品


def test_failure_cleans_partial_outputs(db_ready, tmp_path):
    registry = ModelRegistry(models_dir=tmp_path / "models")
    good_image = _make_image(tmp_path / "good.png")
    missing_image = db.create_image(
        filename="missing.png",
        size_bytes=10,
        format_="png",
        path=str(tmp_path / "nope.png"),
    )
    task_id = tasks_svc.create_task([good_image, missing_image], "restore", {})
    before = {p.name for p in config.OUTPUTS_DIR.iterdir()}

    task = _run_task(task_id, registry)

    assert task["status"] == TaskStatus.FAILED
    assert "nope.png" in task["error"]  # 明确错误信息（原图文件缺失）
    after = {p.name for p in config.OUTPUTS_DIR.iterdir()}
    assert after == before  # 第一张图已落盘的半成品也被清理
    assert not list(config.TMP_DIR.iterdir())  # 中间文件无残留


def test_same_image_multiple_versions_coexist(db_ready, tmp_path):
    registry = ModelRegistry(models_dir=tmp_path / "models")
    image_id = _make_image(tmp_path / "input.png")
    task_a = tasks_svc.create_task([image_id], "restore", {"output_format": "png"})
    task_b = tasks_svc.create_task([image_id], "restore", {"output_format": "jpeg"})

    for task_id in (task_a, task_b):
        task = _run_task(task_id, registry)
        assert task["status"] == TaskStatus.SUCCEEDED

    detail_a = tasks_svc.get_task_detail(task_a)
    detail_b = tasks_svc.get_task_detail(task_b)
    assert detail_a["params_hash"] != detail_b["params_hash"]
    out_a = detail_a["result"]["outputs"][0]
    out_b = detail_b["result"]["outputs"][0]
    assert out_a["path"] != out_b["path"]
    assert out_a["format"] == "png"
    assert out_b["format"] == "jpeg"
    assert Path(out_a["path"]).is_file()
    assert Path(out_b["path"]).is_file()
    assert len(detail_a["result"]["outputs"]) == 1
    assert len(detail_b["result"]["outputs"]) == 1
