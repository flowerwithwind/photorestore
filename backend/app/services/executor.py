"""线程池任务执行器：FIFO 队列 + 可配置并发 + 状态/进度落库。

- 并发默认取 app.config.WORKER_CONCURRENCY（环境变量 PHOTORESTORE_CONCURRENCY，默认 1）；
- POST /api/tasks 只负责入队（task_id + status=queued），执行器消费队列；
- 进度 0~100 单调递增并实时写库，阶段 phase 如 decode/preprocess/infer/postprocess/save；
- 处理器（TaskHandler）可注入：D2 使用 StubTaskHandler 占位，D3 替换为真实管线。
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Protocol

from app.config import WORKER_CONCURRENCY
from app.models import TaskStatus, now_iso
from app.services.task_state import TaskStateError, assert_transition
from app.storage import db
from app.utils.logging import get_logger

logger = get_logger("executor")

PHASES = ("decode", "preprocess", "infer", "postprocess", "save")


class ProgressError(ValueError):
    """进度非法：超出 0~100 或发生回退。"""


class ProgressReporter:
    """单个任务的进度上报器：0~100 单调递增并实时落库。"""

    def __init__(self, task_id: int):
        self._task_id = task_id
        self._progress = 0

    @property
    def progress(self) -> int:
        return self._progress

    def update(self, progress: int, phase: str) -> None:
        if not isinstance(progress, int) or not 0 <= progress <= 100:
            raise ProgressError(f"进度必须在 0~100 之间: {progress!r}")
        if progress < self._progress:
            raise ProgressError(f"进度不能回退: {self._progress} -> {progress}")
        if not phase:
            raise ProgressError("阶段 phase 不能为空")
        db.update_task_progress(self._task_id, progress, phase)
        self._progress = progress


class TaskHandler(Protocol):
    """任务处理器协议：D3 真实管线实现同一接口。"""

    def run(
        self,
        task_id: int,
        image_ids: list[int],
        params: dict[str, Any],
        progress: ProgressReporter,
    ) -> dict[str, Any]:
        """执行任务；成功返回 result，须在结束前上报 progress=100。"""
        ...


class StubTaskHandler:
    """D2 占位处理器：无真实模型，模拟五个阶段的进度推进。"""

    def run(
        self,
        task_id: int,
        image_ids: list[int],
        params: dict[str, Any],
        progress: ProgressReporter,
    ) -> dict[str, Any]:
        step = 100 // len(PHASES)
        for index, phase in enumerate(PHASES, start=1):
            progress.update(index * step, phase)
        return {"ok": True, "task_id": task_id, "outputs": []}


class TaskExecutor:
    """FIFO 任务队列执行器：固定数量 worker 线程消费队列。"""

    def __init__(
        self,
        concurrency: int | None = None,
        handler: TaskHandler | None = None,
    ):
        self._concurrency = max(1, concurrency if concurrency is not None else WORKER_CONCURRENCY)
        self._handler = handler or StubTaskHandler()
        self._queue: queue.Queue[int] = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def start(self) -> None:
        """启动 worker 线程（幂等：重复调用不会重复启动）。"""
        if self._threads:
            return
        for index in range(self._concurrency):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"task-worker-{index}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        """停止执行器：通知 worker 退出并等待收尾。"""
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def enqueue(self, task_id: int) -> None:
        """任务入队（FIFO），立即返回。"""
        self._queue.put(task_id)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._run_task(task_id)
            except Exception:
                logger.exception("执行器内部异常 task_id=%s", task_id)
            finally:
                self._queue.task_done()

    def _run_task(self, task_id: int) -> None:
        task = db.get_task(task_id)
        if task is None or task["status"] != TaskStatus.QUEUED:
            return  # 任务已被删除或取消
        assert_transition(task["status"], TaskStatus.PROCESSING)
        db.update_task_status(task_id, TaskStatus.PROCESSING, started_at=now_iso())
        reporter = ProgressReporter(task_id)
        try:
            result = self._handler.run(task_id, task["image_ids"], task["params"], reporter)
            if self._is_cancelled(task_id):
                return
            assert_transition(
                TaskStatus.PROCESSING, TaskStatus.SUCCEEDED, progress=reporter.progress
            )
            db.update_task_status(
                task_id,
                TaskStatus.SUCCEEDED,
                progress=100,
                result=result,
                finished_at=now_iso(),
            )
            logger.info("任务成功 task_id=%s", task_id)
        except Exception as exc:  # noqa: BLE001 - 处理器异常统一转为 failed
            if self._is_cancelled(task_id):
                return
            try:
                assert_transition(TaskStatus.PROCESSING, TaskStatus.FAILED)
            except TaskStateError:
                return
            db.update_task_status(
                task_id, TaskStatus.FAILED, error=str(exc), finished_at=now_iso()
            )
            logger.error("任务失败 task_id=%s: %s", task_id, exc)

    @staticmethod
    def _is_cancelled(task_id: int) -> bool:
        current = db.get_task(task_id)
        return current is not None and current["status"] == TaskStatus.CANCELLED