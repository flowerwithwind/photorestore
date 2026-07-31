"""任务状态机：queued → processing → succeeded/failed/cancelled。

约定：
- 每个合法转移都带守卫（guard）：例如只有 progress==100 才允许进入 succeeded；
- 非法转移抛出 TaskStateError（409），由统一异常处理器转为错误响应；
- 终态（succeeded/failed/cancelled）不允许再转移。
"""
from __future__ import annotations

from app.models import TaskStatus
from app.utils.errors import AppError

ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.PROCESSING, TaskStatus.CANCELLED},
    TaskStatus.PROCESSING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
}

TERMINAL_STATUSES: set[TaskStatus] = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


class TaskStateError(AppError):
    """非法状态转移（或守卫不满足）时抛出。"""

    def __init__(self, current: TaskStatus | str, target: TaskStatus | str, reason: str = ""):
        message = f"非法状态转移: {current} -> {target}"
        if reason:
            message += f"（{reason}）"
        super().__init__(code="invalid_state_transition", message=message, status_code=409)
        self.current = current
        self.target = target


def can_transition(
    current: TaskStatus | str,
    target: TaskStatus | str,
    *,
    progress: int | None = None,
) -> bool:
    """判断 current -> target 是否合法且满足守卫。"""
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        return False
    # 守卫：只有进度到达 100 的任务才能成功
    return target != TaskStatus.SUCCEEDED or progress == 100


def assert_transition(
    current: TaskStatus | str,
    target: TaskStatus | str,
    *,
    progress: int | None = None,
) -> None:
    """校验转移，非法时抛出 TaskStateError。"""
    if not can_transition(current, target, progress=progress):
        reason = ""
        if target == TaskStatus.SUCCEEDED and progress != 100:
            reason = "succeeded 需要 progress=100"
        raise TaskStateError(current, target, reason)