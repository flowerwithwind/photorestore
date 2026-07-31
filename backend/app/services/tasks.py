"""任务业务服务：创建/查询/取消/重启恢复。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models import TaskStatus, now_iso
from app.services.task_event_bus import task_snapshot
from app.services.task_state import TERMINAL_STATUSES, assert_transition
from app.storage import db
from app.utils.errors import AppError
from app.utils.logging import get_logger

logger = get_logger("tasks")


def compute_params_hash(params: dict[str, Any]) -> str:
    """按 key 排序的规范 JSON 计算参数指纹，用于任务去重/校验。"""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_task(image_ids: list[int], task_type: str, params: dict[str, Any]) -> int:
    """校验图像存在并落库一个 queued 任务（入队由 API 层调用 executor）。"""
    params = validate_task_params(task_type, params)
    missing = [image_id for image_id in image_ids if db.get_image(image_id) is None]
    if missing:
        raise AppError(
            "image_not_found",
            "图像不存在，无法创建任务",
            status_code=404,
            details={"image_ids": missing},
        )
    return db.create_task(
        task_type=task_type,
        status=TaskStatus.QUEUED,
        params=params or {},
        params_hash=compute_params_hash(params or {}),
        image_ids=image_ids,
    )

def validate_task_params(task_type: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """参数校验（D7）：按任务类型检查已知参数语义，非法时抛 AppError(invalid_params, 422)。

    只约束有明确语义的键；未知键透传，便于模型/管线升级兼容。
    """
    raw = dict(params or {})
    errors: list[str] = []

    output_format = raw.get("output_format")
    if output_format is not None and output_format not in {"jpeg", "jpg", "png", "webp"}:
        errors.append(f"output_format 仅支持 jpeg/jpg/png/webp: {output_format!r}")
    quality = raw.get("quality")
    if quality is not None and (
        not isinstance(quality, int) or isinstance(quality, bool) or not 1 <= quality <= 100
    ):
        errors.append(f"quality 必须是 1~100 的整数: {quality!r}")
    timeout = raw.get("timeout_seconds")
    if timeout is not None and (
        not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0
    ):
        errors.append(f"timeout_seconds 必须为正数: {timeout!r}")

    if task_type == "restore":
        engine = raw.get("engine")
        if engine is not None and engine not in {"classic", "realesrgan"}:
            errors.append(f"restore.engine 仅支持 classic/realesrgan: {engine!r}")
        if engine == "realesrgan" and raw.get("scale") not in (2, 4):
            errors.append(f"restore(engine=realesrgan).scale 仅支持 2 或 4: {raw.get('scale')!r}")
        for key, low, high in (("denoise_h", 1, 30), ("denoise_h_color", 1, 30)):
            value = raw.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high
            ):
                errors.append(f"restore.{key} 必须在 {low}~{high}: {value!r}")
        deblur = raw.get("deblur")
        if deblur is not None and not isinstance(deblur, bool):
            errors.append(f"restore.deblur 必须是布尔值: {deblur!r}")
        for key in ("deblur_sigma", "deblur_strength"):
            value = raw.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
            ):
                errors.append(f"restore.{key} 必须为正数: {value!r}")
    elif task_type == "upscale":
        scale = raw.get("scale")
        if scale is not None and scale not in (2, 4):
            errors.append(f"upscale.scale 仅支持 2 或 4: {scale!r}")
    elif task_type == "colorize":
        pass  # 无任务专属参数
    else:
        raise AppError(
            "invalid_task_type",
            f"不支持的任务类型: {task_type!r}",
            status_code=422,
        )

    if errors:
        raise AppError(
            "invalid_params",
            "任务参数校验失败",
            status_code=422,
            details={"errors": errors},
        )
    return raw


def create_tasks_batch(image_ids: list[int], task_type: str, params: dict[str, Any]) -> list[int]:
    """批量创建任务（D7）：先全量校验（参数 + 图像存在性），再单事务原子落库。

    - 任一校验失败整体失败且无残留；
    - 重复 image_id 去重（保持首次出现顺序）；
    - 每张图像独立成任务，便于独立追踪进度与产物。
    """
    validate_task_params(task_type, params)
    unique_ids = list(dict.fromkeys(image_ids))
    missing = [image_id for image_id in unique_ids if db.get_image(image_id) is None]
    if missing:
        raise AppError(
            "image_not_found",
            "图像不存在，无法创建批量任务",
            status_code=404,
            details={"image_ids": missing},
        )
    return db.create_tasks_batch(
        task_type=task_type,
        status=TaskStatus.QUEUED,
        params=params or {},
        params_hash=compute_params_hash(params or {}),
        image_ids=unique_ids,
    )


def rerun_task(task_id: int) -> dict:
    """重跑任务（D7）：复用原任务参数/图像重新入队，生成新 task_id（新版本产物）。

    - 原任务非终态（queued/processing）时返回 409（task_not_terminal），避免重复入队；
    - 新任务与旧任务 params_hash 相同，但产物文件名含新 task_id，互不覆盖。
    """
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在，无法重跑", status_code=404)
    if task["status"] not in TERMINAL_STATUSES:
        raise AppError(
            "task_not_terminal",
            "任务未结束（非终态），不能重跑",
            status_code=409,
            details={"status": task["status"]},
        )
    params = validate_task_params(task["task_type"], task["params"])
    params_hash = compute_params_hash(params)
    new_id = db.create_task(
        task_type=task["task_type"],
        status=TaskStatus.QUEUED,
        params=params,
        params_hash=params_hash,
        image_ids=task["image_ids"],
    )
    logger.info("任务重跑 task_id=%s -> new_task_id=%s", task_id, new_id)
    return {
        "task_id": new_id,
        "status": TaskStatus.QUEUED.value,
        "source_task_id": task_id,
        "params_hash": params_hash,
    }



def list_tasks(status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    return db.list_tasks(status=status, limit=limit, offset=offset)


def get_task_detail(task_id: int) -> dict:
    """任务详情：状态/进度/阶段/参数 + 阶段时间线（phase_logs）+ 结果（含产物）。"""
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    task["phase_logs"] = db.get_phase_logs(task_id)
    return task


def cancel_task(
    task_id: int,
    *,
    executor: Any | None = None,
    event_bus: Any | None = None,
) -> dict:
    """取消任务：queued 直接取消；processing 走协作式中断（executor 设置 cancel 事件）。

    executor.cancel(task_id) 提供线程事件快速信号，DB 状态为最终依据；
    处理链在检查点抛出 TaskCancelledError，由执行器保持 cancelled 并清理。
    """
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    if task["status"] not in (TaskStatus.QUEUED, TaskStatus.PROCESSING):
        # 终态不允许再取消 → 409
        assert_transition(task["status"], TaskStatus.CANCELLED)
    status = task["status"]
    # 先设置取消事件：覆盖“cancel 读到 queued 时执行器已拾起”的竞态窗口，
    # 处理链会在下一个检查点（progress.check_cancel）中断
    if executor is not None:
        executor.cancel(task_id)
    # 条件更新：仅从读到的状态迁移，避免覆盖并发写入的新状态
    ok = db.update_task_status(
        task_id,
        TaskStatus.CANCELLED,
        finished_at=now_iso(),
        expected_status=status,
    )
    if not ok:
        # 读后被并发迁移（多为 queued→processing）：按最新状态重试一次
        task = db.get_task(task_id)
        if task is None:
            raise AppError("task_not_found", "任务不存在", status_code=404)
        if task["status"] in (TaskStatus.QUEUED, TaskStatus.PROCESSING):
            ok = db.update_task_status(
                task_id,
                TaskStatus.CANCELLED,
                finished_at=now_iso(),
                expected_status=task["status"],
            )
        else:
            ok = True  # 已进入终态（succeeded/failed），保留现状
    if ok:
        _publish_and_close(event_bus, task_id)
    return db.get_task(task_id)


def _publish_and_close(event_bus: Any | None, task_id: int) -> None:
    """终态事件发布 + 关闭事件流（无总线时静默跳过）。"""
    if event_bus is None:
        return
    task = db.get_task(task_id)
    if task is not None:
        event_bus.publish(task_id, task_snapshot(task))
    event_bus.close(task_id)


def recover_interrupted_tasks() -> int:
    """应用启动时调用：把遗留 processing 任务标记为 failed（原因 restart）。

    返回被恢复（标记为失败）的任务数量。
    """
    count = 0
    for task in db.list_tasks(status=TaskStatus.PROCESSING):
        db.update_task_status(
            task["id"],
            TaskStatus.FAILED,
            error="restart: 服务重启导致任务中断",
            finished_at=now_iso(),
        )
        count += 1
    if count:
        logger.warning("重启恢复：%s 个 processing 任务已标记为 failed(restart)", count)
    return count