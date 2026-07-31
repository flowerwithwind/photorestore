"""D4 真实任务处理器：D3 统一管线 + 阶段进度 + 产物落盘 + 协作式取消。

职责：
- 按 images 记录读取原图文件 → process_image（decode/preprocess/infer/postprocess 分阶段进度）；
- 检查点（progress.check_cancel）支持 processing 中取消；
- 产物写入 outputs/（先写 tmp 再原子替换），命名含 image_id + params_hash 前缀，
  同一原图多次入队不同参数时产物共存互不覆盖；
- 成功返回 result（模型名、前后尺寸/体积、产物路径与下载 URL）；
- 失败/取消时清理本任务已落盘的中间文件与半成品产物。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app import config
from app.services import image_pipeline
from app.services.model_registry import ModelRegistry, default_registry
from app.storage import db
from app.utils.errors import AppError
from app.utils.logging import get_logger

logger = get_logger("pipeline_handler")


class PipelineTaskHandler:
    """TaskHandler 协议实现：默认执行器处理器（替换 D2 StubTaskHandler）。"""

    def __init__(self, registry: ModelRegistry | None = None):
        self._registry = registry or default_registry

    def run(
        self,
        task_id: int,
        image_ids: list[int],
        params: dict[str, Any],
        progress: Any,
    ) -> dict[str, Any]:
        task = db.get_task(task_id)
        if task is None:
            raise AppError("task_not_found", "任务不存在，无法处理", status_code=404)
        task_type = task["task_type"]
        params_hash = task["params_hash"]
        model_name = self._registry.get_model(task_type, params).name
        created: list[Path] = []
        staged: list[Path] = []
        try:
            outputs: list[dict[str, Any]] = []
            for image_id in image_ids:
                progress.check_cancel()
                image = db.get_image(image_id)
                if image is None:
                    raise AppError(
                        "image_not_found",
                        "原图不存在，无法处理",
                        status_code=404,
                        details={"image_id": image_id},
                    )
                source = Path(image["path"])
                if not source.is_file():
                    raise AppError(
                        "image_file_missing",
                        f"原图文件缺失: {source}",
                        status_code=404,
                        details={"image_id": image_id},
                    )
                data = source.read_bytes()
                progress.check_cancel()
                processed = image_pipeline.process_image(
                    data,
                    task_type,
                    params,
                    progress_cb=lambda percent, phase: self._on_progress(
                        progress, percent, phase
                    ),
                    registry=self._registry,
                )
                progress.check_cancel()
                final, tmp = self._stage_output(task_id, image_id, params_hash, processed)
                staged.append(tmp)
                os.replace(tmp, final)
                created.append(final)
                outputs.append(
                    self._output_entry(task_id, image_id, model_name, processed, final, len(outputs))
                )
            progress.check_cancel()
            progress.update(100, "save")
            return {
                "task_type": task_type,
                "params_hash": params_hash,
                "model": model_name,
                "outputs": outputs,
            }
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            for path in staged:
                path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _on_progress(progress: Any, percent: int, phase: str) -> None:
        progress.check_cancel()
        progress.update(percent, phase)

    @staticmethod
    def _stage_output(
        task_id: int,
        image_id: int,
        params_hash: str,
        processed: image_pipeline.ProcessedImage,
    ) -> tuple[Path, Path]:
        name = f"img{image_id}_p{params_hash[:8]}_t{task_id}.{processed.format}"
        final = config.OUTPUTS_DIR / name
        tmp = config.TMP_DIR / name
        tmp.write_bytes(processed.image_bytes)
        return final, tmp

    @staticmethod
    def _output_entry(
        task_id: int,
        image_id: int,
        model_name: str,
        processed: image_pipeline.ProcessedImage,
        final: Path,
        index: int,
    ) -> dict[str, Any]:
        return {
            "image_id": image_id,
            "filename": final.name,
            "path": str(final),
            "download_url": f"/api/tasks/{task_id}/outputs/{index}/download",
            "format": processed.format,
            "width": processed.width,
            "height": processed.height,
            "size_bytes": len(processed.image_bytes),
            "input_width": processed.metrics.input_width,
            "input_height": processed.metrics.input_height,
            "input_size_bytes": processed.metrics.input_size_bytes,
            "input_format": processed.metrics.input_format,
            "model": model_name,
        }
