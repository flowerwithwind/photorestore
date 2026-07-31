"""统一管线测试：端到端（Mock 模型）、进度回调、超时、缺模型、EXIF/缩放（hermetic）。"""
from __future__ import annotations

import io
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime
import pytest
from PIL import Image

from app.services.image_pipeline import (
    InferenceTimeoutError,
    ProcessedImage,
    process_image,
    run_with_timeout,
)
from app.services.model_registry import (
    ModelNotFoundError,
    ModelRegistry,
    UnknownTaskTypeError,
)

EXIF_ORIENTATION_TAG = 0x0112


def _png_bytes(width: int = 16, height: int = 12) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (80, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_with_orientation(width: int, height: int, orientation: int) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (width, height), (200, 30, 40))
    exif = Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_process_image_restore_end_to_end():
    result = process_image(_png_bytes(), "restore", {})
    assert isinstance(result, ProcessedImage)
    assert result.format == "jpeg"
    assert (result.width, result.height) == (16, 12)
    assert result.task_type == "restore"
    assert result.image_bytes.startswith(b"\xff\xd8")
    assert result.metrics.input_format == "png"
    assert result.metrics.input_size_bytes > 0
    assert result.metrics.output_size_bytes == len(result.image_bytes)
    assert result.metrics.output_format == "jpeg"
    assert result.metrics.output_width == 16


def test_process_image_progress_callback_monotonic():
    events: list[tuple[int, str]] = []

    def progress_cb(percent: int, phase: str) -> None:
        events.append((percent, phase))

    process_image(_png_bytes(), "restore", {}, progress_cb=progress_cb)
    percents = [percent for percent, _ in events]
    assert percents == sorted(percents)
    assert events[0][1] == "decode"
    assert {phase for _, phase in events} >= {"decode", "preprocess", "infer", "postprocess"}
    assert events[-1] == (95, "postprocess")


def test_process_image_exif_orientation():
    result = process_image(_jpeg_with_orientation(20, 10, 6), "restore", {})
    assert (result.width, result.height) == (10, 20)


def test_process_image_scaling_limit():
    result = process_image(_png_bytes(200, 100), "restore", {}, max_dimension=50)
    assert (result.width, result.height) == (50, 25)


def test_process_image_output_format_params():
    result = process_image(_png_bytes(), "restore", {"output_format": "png"})
    assert result.format == "png"
    assert result.image_bytes.startswith(b"\x89PNG")


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


class FakeColorizeSession:
    """假 ONNX 会话：上色返回同尺寸全零 ab 张量。"""

    def __init__(self, path, providers=None):
        self.path = Path(str(path))

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        arr = input_feed["input"]
        return [np.zeros((1, 2, arr.shape[2], arr.shape[3]), dtype=np.float32)]


def test_process_image_upscale_mock_model_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeUpscaleSession)
    (tmp_path / "realesrgan-x2.onnx").write_bytes(b"fake-onnx")
    registry = ModelRegistry(models_dir=tmp_path)
    result = process_image(_png_bytes(8, 6), "upscale", {"scale": 2}, registry=registry)
    assert (result.width, result.height) == (16, 12)
    assert result.task_type == "upscale"
    assert result.metrics.output_width == 16
    assert result.metrics.output_size_bytes == len(result.image_bytes)


def test_process_image_colorize_mock_model_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeColorizeSession)
    (tmp_path / "ddcolor.onnx").write_bytes(b"fake-onnx")
    registry = ModelRegistry(models_dir=tmp_path)
    result = process_image(_png_bytes(8, 6), "colorize", {}, registry=registry)
    assert (result.width, result.height) == (8, 6)
    assert result.task_type == "colorize"


def test_process_image_missing_model_error(tmp_path):
    registry = ModelRegistry(models_dir=tmp_path)
    with pytest.raises(ModelNotFoundError) as excinfo:
        process_image(_png_bytes(), "upscale", {"scale": 2}, registry=registry)
    assert "download_models.py" in str(excinfo.value)


def test_process_image_unknown_task_type():
    with pytest.raises(UnknownTaskTypeError):
        process_image(_png_bytes(), "enhance", {})


class SlowRunner:
    """慢速假模型：用于超时测试。"""

    name = "slow-mock"

    def run(self, rgb, progress_cb=None):
        time.sleep(0.3)
        return rgb


class StubRegistry:
    """只返回固定 runner 的假注册表。"""

    def __init__(self, runner):
        self._runner = runner

    def get_model(self, task_type, params=None):
        return self._runner


def test_process_image_inference_timeout():
    registry = StubRegistry(SlowRunner())
    with pytest.raises(InferenceTimeoutError):
        process_image(_png_bytes(), "restore", {"timeout_seconds": 0.05}, registry=registry)


def test_run_with_timeout_returns_value():
    assert run_with_timeout(lambda: 42, 1.0) == 42
