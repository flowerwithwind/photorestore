"""Pydantic 数据模型与枚举。"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def now_iso() -> str:
    # 全项目统一使用本地时间（无时区），避免 UI 展示混乱
    return datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005


class TaskType(StrEnum):
    RESTORE = "restore"
    UPSCALE = "upscale"
    COLORIZE = "colorize"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    """D2 启用；D1 预留接口契约。"""

    image_ids: list[int] = Field(default_factory=list, min_length=1)
    task_type: TaskType
    params: dict[str, Any] = Field(default_factory=dict)


class BatchTaskCreate(BaseModel):
    """D7 批量任务请求：多图同参数，原子创建（任一校验失败整体失败、无残留）。"""

    image_ids: list[int] = Field(default_factory=list, min_length=1)
    task_type: TaskType
    params: dict[str, Any] = Field(default_factory=dict)
