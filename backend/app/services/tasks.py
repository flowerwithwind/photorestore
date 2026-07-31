"""任务业务服务：创建/查询/取消/重启恢复。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models import TaskStatus, now_iso
from app.services.task_state import TaskStateError, assert_transition
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


def list_tasks(status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    return db.list_tasks(status=status, limit=limit, offset=offset)


def get_task_detail(task_id: int) -> dict:
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    return task


def cancel_task(task_id: int) -> dict:
    """取消任务：仅 queued 可取消；processing 暂不支持中断（需处理器协作，D3 细化）。"""
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    if task["status"] == TaskStatus.PROCESSING:
        raise TaskStateError(
            TaskStatus.PROCESSING, TaskStatus.CANCELLED, reason="任务正在处理中，暂不支持中断"
        )
    assert_transition(task["status"], TaskStatus.CANCELLED)
    db.update_task_status(task_id, TaskStatus.CANCELLED, finished_at=now_iso())
    return db.get_task(task_id)


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