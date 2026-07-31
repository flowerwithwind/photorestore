"""模型注册表测试：按类型路由 / 单例缓存 / 缺模型报错 / Mock ONNX 会话（hermetic）。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime
import pytest

from app.services.model_registry import (
    ClassicRestoreRunner,
    DDColorRunner,
    ModelNotFoundError,
    ModelRegistry,
    RealESRGANRunner,
    UnknownTaskTypeError,
    classic_deblur,
)


def _rgb(shape: tuple[int, int] = (12, 16)) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, size=(*shape, 3), dtype=np.uint8)


@pytest.fixture()
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(models_dir=tmp_path)


def test_registry_routes_by_task_type(registry, tmp_path):
    restore = registry.get_model("restore")
    assert isinstance(restore, ClassicRestoreRunner)
    upscale2 = registry.get_model("upscale", {"scale": 2})
    assert isinstance(upscale2, RealESRGANRunner)
    assert upscale2.scale == 2
    assert upscale2.model_path == tmp_path / "realesrgan-x2.onnx"
    upscale4 = registry.get_model("upscale", {"scale": 4})
    assert upscale4.scale == 4
    colorize = registry.get_model("colorize")
    assert isinstance(colorize, DDColorRunner)
    assert colorize.model_path == tmp_path / "ddcolor.onnx"


def test_registry_restore_realesrgan_optional(registry):
    runner = registry.get_model("restore", {"engine": "realesrgan", "scale": 4})
    assert isinstance(runner, RealESRGANRunner)
    assert runner.scale == 4


def test_registry_unknown_task_type(registry):
    with pytest.raises(UnknownTaskTypeError) as excinfo:
        registry.get_model("enhance")
    assert "enhance" in str(excinfo.value)
    assert "restore" in str(excinfo.value)


def test_registry_upscale_invalid_scale(registry):
    with pytest.raises(ValueError):
        registry.get_model("upscale", {"scale": 3})


def test_registry_singleton_cache(registry):
    first = registry.get_model("colorize")
    assert registry.get_model("colorize") is first
    assert (
        registry.get_model("upscale", {"scale": 2})
        is registry.get_model("upscale", {"scale": 2})
    )
    assert (
        registry.get_model("upscale", {"scale": 2})
        is not registry.get_model("upscale", {"scale": 4})
    )
    registry.clear_cache()
    assert registry.get_model("colorize") is not first


def test_restore_classic_works_without_model_files():
    runner = ClassicRestoreRunner({"deblur": True})
    out = runner.run(_rgb())
    assert out.shape == (12, 16, 3)
    assert out.dtype == np.uint8


def test_classic_deblur_preserves_shape():
    out = classic_deblur(_rgb(shape=(16, 16)))
    assert out.shape == (16, 16, 3)
    assert out.dtype == np.uint8
    assert np.isfinite(out.astype(np.float32)).all()


@pytest.mark.parametrize(
    ("task_type", "params"),
    [
        ("restore", {"engine": "realesrgan"}),
        ("upscale", {"scale": 2}),
        ("colorize", {}),
    ],
)
def test_missing_model_error_hints_download(registry, task_type, params):
    runner = registry.get_model(task_type, params)
    with pytest.raises(ModelNotFoundError) as excinfo:
        runner.run(_rgb())
    message = str(excinfo.value)
    assert "download_models.py" in message
    assert "models" in message


class FakeOnnxSession:
    """hermetic 假 ONNX 会话：按文件名推断 scale，返回全零输出。"""

    def __init__(self, path, providers=None):
        self.path = Path(str(path))
        self.last_input = None

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        self.last_input = input_feed
        arr = input_feed["input"]
        if self.path.name.startswith("realesrgan"):
            scale = int(self.path.stem.rsplit("x", 1)[1])
            out = np.zeros(
                (1, 3, arr.shape[2] * scale, arr.shape[3] * scale), dtype=np.float32
            )
        else:
            out = np.zeros((1, 2, arr.shape[2], arr.shape[3]), dtype=np.float32)
        return [out]


def test_realesrgan_runs_with_fake_session(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeOnnxSession)
    (tmp_path / "realesrgan-x2.onnx").write_bytes(b"fake-onnx")
    runner = RealESRGANRunner(tmp_path, scale=2)
    out = runner.run(_rgb(shape=(10, 12)))
    assert out.shape == (20, 24, 3)
    assert out.dtype == np.uint8


def test_realesrgan_runs_with_fake_session_x4(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeOnnxSession)
    (tmp_path / "realesrgan-x4.onnx").write_bytes(b"fake-onnx")
    runner = RealESRGANRunner(tmp_path, scale=4)
    out = runner.run(_rgb(shape=(8, 10)))
    assert out.shape == (32, 40, 3)


def test_ddcolor_runs_with_fake_session(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeOnnxSession)
    (tmp_path / "ddcolor.onnx").write_bytes(b"fake-onnx")
    runner = DDColorRunner(tmp_path)
    rgb = _rgb(shape=(10, 12))
    out = runner.run(rgb)
    assert out.shape == (10, 12, 3)
    # ab=0 -> 中性灰：三通道近似一致（允许 cv2 LAB 往返舍入误差）
    diff = int(np.abs(out[:, :, 0].astype(np.int16) - out[:, :, 1].astype(np.int16)).max())
    assert diff <= 2
    diff2 = int(np.abs(out[:, :, 1].astype(np.int16) - out[:, :, 2].astype(np.int16)).max())
    assert diff2 <= 2


def test_onnx_runner_caches_session(tmp_path, monkeypatch):
    monkeypatch.setattr(onnxruntime, "InferenceSession", FakeOnnxSession)
    (tmp_path / "ddcolor.onnx").write_bytes(b"fake-onnx")
    runner = DDColorRunner(tmp_path)
    runner.run(_rgb(shape=(6, 6)))
    session = runner._session
    assert session is not None
    runner.run(_rgb(shape=(6, 6)))
    assert runner._session is session
    runner.clear()
    assert runner._session is None
