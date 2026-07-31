"""模型注册表：按任务类型路由 + 按需加载 + 单例缓存。

支持的任务类型：
- restore   去噪/去模糊：OpenCV 经典算法保底（fastNlMeansDenoising + 维纳去模糊），
            可选 Real-ESRGAN ONNX（params 传 engine=realesrgan）；
- upscale   超分辨率：Real-ESRGAN ONNX ×2/×4（params 传 scale=2/4，默认 2）；
- colorize  黑白上色：DDColor ONNX（等价替代模型可扩展为同一 Runner 接口）。

设计约定：
- Runner 统一推理接口 run(rgb_hwc_uint8, progress_cb) -> rgb_hwc_uint8；
- 模型文件按需惰性加载，同一 (task_type, 关键参数) 复用单例；
- 模型缺失抛 ModelNotFoundError，错误信息提示运行 scripts/download_models.py。
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import onnxruntime

from app.config import MODEL_META, MODELS_DIR, SUPPORTED_TASK_TYPES
from app.utils.logging import get_logger

logger = get_logger("model_registry")

ProgressCallback = Callable[[int, str], None]
DOWNLOAD_HINT = "请运行 scripts/download_models.py 下载模型后重试"


class UnknownTaskTypeError(ValueError):
    """任务类型不在注册表支持范围内。"""

    def __init__(self, task_type: str):
        super().__init__(
            f"不支持的任务类型: {task_type!r}（可选: {', '.join(SUPPORTED_TASK_TYPES)}）"
        )
        self.task_type = task_type


class ModelNotFoundError(RuntimeError):
    """模型文件缺失：需先运行 scripts/download_models.py。"""


class ModelLoadError(RuntimeError):
    """模型文件存在但加载失败（格式损坏或与 onnxruntime 不兼容）。"""


class ModelRunner(Protocol):
    """统一推理接口：numpy RGB 进、numpy RGB 出，可选进度回调。"""

    name: str

    def run(
        self,
        rgb: np.ndarray,
        progress_cb: ProgressCallback | None = None,
    ) -> np.ndarray:
        ...


def _params_fingerprint(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _gaussian_kernel(sigma: float, size: int) -> np.ndarray:
    """高斯 PSF：一维核外积后归一化。"""
    axis = np.arange(size) - size // 2
    kernel_1d = np.exp(-(axis.astype(np.float32) ** 2) / (2.0 * sigma * sigma))
    kernel = np.outer(kernel_1d, kernel_1d)
    return kernel / kernel.sum()


def _wiener_deblur_channel(channel: np.ndarray, kernel: np.ndarray, strength: float) -> np.ndarray:
    """单通道维纳滤波去模糊（FFT 域，纯 numpy 实现）。"""
    fft_channel = np.fft.fft2(channel.astype(np.float32))
    fft_kernel = np.fft.fft2(kernel.astype(np.float32), s=channel.shape)
    kernel_conj = np.conj(fft_kernel)
    denominator = np.abs(fft_kernel) ** 2 + strength
    restored = np.fft.ifft2(fft_channel * kernel_conj / denominator).real
    return np.clip(restored, 0.0, 255.0).astype(np.uint8)


def classic_deblur(rgb: np.ndarray, sigma: float = 1.5, strength: float = 0.02) -> np.ndarray:
    """维纳滤波去模糊（高斯 PSF 假设），返回同尺寸 RGB uint8。"""
    size = max(3, round(sigma * 6) | 1)
    kernel = _gaussian_kernel(sigma, size)
    channels = [_wiener_deblur_channel(rgb[:, :, c], kernel, strength) for c in range(3)]
    return np.dstack(channels)


def classic_denoise(rgb: np.ndarray, h: float = 5.0, h_color: float = 5.0) -> np.ndarray:
    """OpenCV fastNlMeansDenoisingColored 彩色去噪（经典保底算法）。"""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    denoised = cv2.fastNlMeansDenoisingColored(bgr, None, h, h_color, 7, 21)
    return cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)


class ClassicRestoreRunner:
    """restore 保底引擎：去噪常开，去模糊按 params.deblur 开启（默认关闭）。"""

    name = "classic-restore"

    def __init__(self, params: dict[str, Any] | None = None):
        self._params = dict(params or {})

    def run(
        self,
        rgb: np.ndarray,
        progress_cb: ProgressCallback | None = None,
    ) -> np.ndarray:
        if progress_cb is not None:
            progress_cb(10, "infer")
        output = rgb
        if self._params.get("deblur", False):
            output = classic_deblur(
                output,
                sigma=float(self._params.get("deblur_sigma", 1.5)),
                strength=float(self._params.get("deblur_strength", 0.02)),
            )
        output = classic_denoise(
            output,
            h=float(self._params.get("denoise_h", 5.0)),
            h_color=float(self._params.get("denoise_h_color", 5.0)),
        )
        if progress_cb is not None:
            progress_cb(100, "infer")
        return output


class _OnnxRunner:
    """ONNX Runner 骨架：按需加载 + 线程安全单例缓存 + 缺失/加载失败明确报错。"""

    file_name: str = ""
    task_name: str = ""

    def __init__(self, models_dir: Path):
        self._models_dir = Path(models_dir)
        self._session: onnxruntime.InferenceSession | None = None
        self._lock = threading.Lock()

    @property
    def model_path(self) -> Path:
        return self._models_dir / self.file_name

    def _ensure_session(self) -> onnxruntime.InferenceSession:
        path = self.model_path
        if not path.is_file():
            raise ModelNotFoundError(f"{self.task_name}模型文件缺失: {path}；{DOWNLOAD_HINT}")
        if self._session is None:
            with self._lock:
                if self._session is None:
                    try:
                        self._session = onnxruntime.InferenceSession(
                            str(path), providers=["CPUExecutionProvider"]
                        )
                    except Exception as exc:
                        raise ModelLoadError(f"{self.task_name}模型加载失败: {path}（{exc}）") from exc
        return self._session

    def clear(self) -> None:
        """释放缓存的 session（测试隔离或热更新用）。"""
        with self._lock:
            self._session = None


class RealESRGANRunner(_OnnxRunner):
    """Real-ESRGAN ONNX 超分：输入 RGB 归一化 NCHW，输出按 scale 校验并兜底缩放。"""

    name = "realesrgan"

    def __init__(self, models_dir: Path, scale: int):
        super().__init__(models_dir)
        self.scale = scale
        self.file_name = f"realesrgan-x{scale}.onnx"
        self.task_name = f"Real-ESRGAN ×{scale}"

    def run(
        self,
        rgb: np.ndarray,
        progress_cb: ProgressCallback | None = None,
    ) -> np.ndarray:
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError(f"Real-ESRGAN 输入必须是 HWC 三通道: {rgb.shape}")
        height, width = rgb.shape[:2]
        if progress_cb is not None:
            progress_cb(5, "infer")
        session = self._ensure_session()
        input_meta = session.get_inputs()[0]
        input_feed = np.ascontiguousarray(rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[
            None
        ]
        if progress_cb is not None:
            progress_cb(50, "infer")
        outputs = session.run(None, {input_meta.name: input_feed})
        if progress_cb is not None:
            progress_cb(90, "infer")
        tensor = outputs[0]
        if tensor.ndim != 4 or tensor.shape[0] != 1:
            raise ModelLoadError(f"{self.task_name}输出形状异常: {tensor.shape}")
        expected_h, expected_w = height * self.scale, width * self.scale
        result = tensor[0].transpose(1, 2, 0)
        if result.shape[:2] != (expected_h, expected_w):
            # 兜底：个别导出不含上采样层，按目标尺寸缩放对齐
            result = cv2.resize(result, (expected_w, expected_h), interpolation=cv2.INTER_CUBIC)
        result = np.clip(result, 0.0, 1.0)
        output = (result * 255.0 + 0.5).astype(np.uint8)
        if progress_cb is not None:
            progress_cb(100, "infer")
        return output


class DDColorRunner(_OnnxRunner):
    """DDColor ONNX 黑白上色：L（Lab）进、ab 出，合成 Lab 后转 RGB。

    约定：输入为 L/255（NCHW float32，与 cv2 uint8 LAB 的 L 通道一致）；
    输出为 ab 两通道（归一化 [-1,1]），经 128 系数还原到 cv2 LAB 表示。
    等价替代模型实现同一 Runner 接口即可接入。
    """

    name = "ddcolor"

    def __init__(self, models_dir: Path):
        super().__init__(models_dir)
        self.file_name = "ddcolor.onnx"
        self.task_name = "DDColor"

    def run(
        self,
        rgb: np.ndarray,
        progress_cb: ProgressCallback | None = None,
    ) -> np.ndarray:
        height, width = rgb.shape[:2]
        if progress_cb is not None:
            progress_cb(5, "infer")
        session = self._ensure_session()
        input_meta = session.get_inputs()[0]
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        l_channel = lab[:, :, 0].astype(np.float32)
        input_feed = (l_channel / 255.0)[None, None, :, :]
        if progress_cb is not None:
            progress_cb(50, "infer")
        outputs = session.run(None, {input_meta.name: input_feed})
        if progress_cb is not None:
            progress_cb(90, "infer")
        tensor = outputs[0]
        if tensor.ndim != 4 or tensor.shape[0] != 1 or tensor.shape[1] != 2:
            raise ModelLoadError(f"{self.task_name}输出形状异常: {tensor.shape}")
        ab = tensor[0].transpose(1, 2, 0)
        if ab.shape[:2] != (height, width):
            ab = cv2.resize(ab, (width, height), interpolation=cv2.INTER_LINEAR)
        ab = np.clip(ab, -1.0, 1.0) * 128.0 + 128.0
        colored_lab = np.dstack((l_channel, ab[:, :, 0], ab[:, :, 1])).astype(np.uint8)
        output = cv2.cvtColor(colored_lab, cv2.COLOR_LAB2RGB)
        if progress_cb is not None:
            progress_cb(100, "infer")
        return output


class ModelRegistry:
    """模型注册表：按任务类型路由，Runner 惰性加载并单例缓存。"""

    def __init__(self, models_dir: Path | None = None):
        self._models_dir = Path(models_dir) if models_dir is not None else MODELS_DIR
        self._cache: dict[str, ModelRunner] = {}
        self._lock = threading.Lock()

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @property
    def task_types(self) -> tuple[str, ...]:
        return SUPPORTED_TASK_TYPES

    def clear_cache(self) -> None:
        """清空 Runner 单例缓存（测试隔离或热更新用）。"""
        with self._lock:
            self._cache.clear()

    def get_model(self, task_type: str, params: dict[str, Any] | None = None) -> ModelRunner:
        """按任务类型路由并返回 Runner；模型文件在 run() 时才惰性加载。"""
        params = dict(params or {})
        if task_type == "restore":
            if params.get("engine") == "realesrgan":
                scale = int(params.get("scale", 4))
                if scale not in (2, 4):
                    raise ValueError(
                        f"restore 的 Real-ESRGAN 仅支持 scale=2 或 scale=4: {scale!r}"
                    )
                return self._cached(
                    f"restore:realesrgan:x{scale}",
                    lambda: RealESRGANRunner(self._models_dir, scale),
                )
            key = f"restore:classic:{_params_fingerprint(params)}"
            return self._cached(key, lambda: ClassicRestoreRunner(params))
        if task_type == "upscale":
            scale = int(params.get("scale", 2))
            if scale not in (2, 4):
                raise ValueError(f"upscale 仅支持 scale=2 或 scale=4: {scale!r}")
            return self._cached(
                f"upscale:realesrgan:x{scale}",
                lambda: RealESRGANRunner(self._models_dir, scale),
            )
        if task_type == "colorize":
            return self._cached("colorize:ddcolor", lambda: DDColorRunner(self._models_dir))
        raise UnknownTaskTypeError(task_type)

    def _cached(self, key: str, factory: Callable[[], ModelRunner]) -> ModelRunner:
        with self._lock:
            runner = self._cache.get(key)
            if runner is None:
                runner = factory()
                self._cache[key] = runner
            return runner


default_registry = ModelRegistry()

def get_model_status(models_dir: Path | None = None) -> dict:
    """只读模型元数据：按任务类型统计模型文件存在性、体积与就绪状态。

    数据来源：config.MODEL_META + models/ 目录实际文件扫描；
    仅用于设置页展示与 API 元数据，不加载模型、不修改任何文件。
    """
    directory = Path(models_dir) if models_dir is not None else MODELS_DIR
    known_files = {name for meta in MODEL_META.values() for name in meta["files"]}
    items: list[dict] = []
    for key, meta in MODEL_META.items():
        file_infos: list[dict] = []
        total_bytes = 0
        missing: list[str] = []
        for name in meta["files"]:
            path = directory / name
            exists = path.is_file()
            size_bytes = path.stat().st_size if exists else 0
            if exists:
                total_bytes += size_bytes
            else:
                missing.append(name)
            file_infos.append({"name": name, "exists": exists, "size_bytes": size_bytes})
        items.append(
            {
                "key": key,
                "name": meta["name"],
                "engine": meta["engine"],
                "required": bool(meta["required"]),
                "description": meta.get("description", ""),
                "files": file_infos,
                "total_bytes": total_bytes,
                "missing": missing,
                "ready": not missing,
                "download_hint": f"python scripts/download_models.py --only {key}",
            }
        )
    extra_files: list[dict] = []
    total_bytes = 0
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.name not in known_files:
                extra_files.append({"name": path.name, "size_bytes": path.stat().st_size})
            else:
                # 同名文件可能被多个任务类型共享，只按磁盘实际文件计一次体积
                total_bytes += path.stat().st_size
    ready = sum(1 for item in items if item["ready"])
    return {
        "models_dir": str(directory),
        "items": items,
        "extra_files": extra_files,
        "summary": {
            "total": len(items),
            "ready": ready,
            "missing": len(items) - ready,
            "total_bytes": total_bytes,
        },
    }
