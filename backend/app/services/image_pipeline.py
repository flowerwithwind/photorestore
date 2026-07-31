"""D3 统一图像管线：图像服务层 + 模型注册表编排，供 D4 任务执行器接入。

对外主入口：
    process_image(image_bytes, task_type, params, progress_cb) -> ProcessedImage

进度回调约定：progress_cb(percent, phase)，phase 与 D2 执行器阶段一致
（decode/preprocess/infer/postprocess），0~100 单调递增；管线结束于 95
（postprocess），save/100 由调用方在落盘后上报。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from app.config import MAX_IMAGE_DIMENSION, OUTPUT_QUALITY, TASK_TIMEOUT_SECONDS
from app.services import image_io
from app.services.model_registry import (
    SUPPORTED_TASK_TYPES,
    ModelRegistry,
    ModelRunner,
    ProgressCallback,
    UnknownTaskTypeError,
    default_registry,
)
from app.utils.logging import get_logger

logger = get_logger("image_pipeline")

# 各阶段进度权重（单调递增，phase 与 D2 PHASES 对齐）
_DECODE_PROGRESS = 5
_PREPROCESS_PROGRESS = 30
_INFER_START_PROGRESS = 35
_POSTPROCESS_START_PROGRESS = 90
_POSTPROCESS_END_PROGRESS = 95


class InferenceTimeoutError(TimeoutError):
    """推理超时：超过 params.timeout_seconds 或全局 TASK_TIMEOUT_SECONDS。"""


@dataclass(frozen=True)
class ProcessedImage:
    """管线结果：编码字节 + 尺寸/体积记录（供 D4 落库与磁盘统计）。"""

    image_bytes: bytes
    format: str
    width: int
    height: int
    task_type: str
    metrics: image_io.ImageMetrics


def run_with_timeout(
    fn: Callable[[], Any],
    timeout_seconds: float,
    description: str = "推理",
) -> Any:
    """在独立线程执行并等待；超时抛 InferenceTimeoutError（线程留待自然结束）。"""
    box: dict[str, Any] = {}

    def wrapper() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 需把异常传回主线程
            box["error"] = exc

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise InferenceTimeoutError(f"{description}超时（超过 {timeout_seconds:g}s）")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def process_image(
    image_bytes: bytes,
    task_type: str,
    params: dict[str, Any] | None = None,
    progress_cb: ProgressCallback | None = None,
    *,
    registry: ModelRegistry | None = None,
    max_dimension: int | None = None,
    output_format: str | None = None,
    quality: int | None = None,
) -> ProcessedImage:
    """端到端处理单张图像：解码/EXIF/缩放/RGB -> 模型推理 -> 后处理编码。"""
    if task_type not in SUPPORTED_TASK_TYPES:
        raise UnknownTaskTypeError(task_type)
    params = dict(params or {})
    timeout = float(params.get("timeout_seconds", TASK_TIMEOUT_SECONDS))
    if timeout <= 0:
        raise ValueError(f"timeout_seconds 必须为正数: {timeout!r}")

    def report(percent: int, phase: str) -> None:
        if progress_cb is not None:
            progress_cb(percent, phase)

    report(_DECODE_PROGRESS, "decode")
    rgb, metrics = image_io.preprocess_image(
        image_bytes, max_dimension=max_dimension or MAX_IMAGE_DIMENSION
    )
    report(_PREPROCESS_PROGRESS, "preprocess")

    model: ModelRunner = (registry or default_registry).get_model(task_type, params)

    def infer() -> np.ndarray:
        return model.run(
            rgb,
            progress_cb=lambda p, _phase: report(
                _INFER_START_PROGRESS + int(p * 0.5), "infer"
            ),
        )

    report(_INFER_START_PROGRESS, "infer")
    output = run_with_timeout(infer, timeout, description=f"{task_type} 推理")

    report(_POSTPROCESS_START_PROGRESS, "postprocess")
    fmt = output_format or str(params.get("output_format", "jpeg"))
    quality_value = quality if quality is not None else int(params.get("quality", OUTPUT_QUALITY))
    data, canonical = image_io.postprocess_array(output, fmt, quality_value)
    report(_POSTPROCESS_END_PROGRESS, "postprocess")

    height, width = output.shape[:2]
    result_metrics = replace(
        metrics,
        output_width=width,
        output_height=height,
        output_format=canonical,
        output_size_bytes=len(data),
    )
    return ProcessedImage(
        image_bytes=data,
        format=canonical,
        width=width,
        height=height,
        task_type=task_type,
        metrics=result_metrics,
    )
