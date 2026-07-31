"""任务队列执行器：FIFO 队列 + 可配置并发 + 状态/进度落库 + 协作式取消（D4）。

- 并发默认 app.config.WORKER_CONCURRENCY（PHOTORESTORE_CONCURRENCY，默认 1）；
- POST /api/tasks 只负责入队（task_id + status=queued），执行器消费队列；
- 进度 0~100 单调递增并实时写库，阶段 phase 为 decode/preprocess/infer/postprocess/save；
- 进度更新同时记录阶段时间线（task_phase_logs）并发布 SSE 快照到事件总线；
- 处理器（TaskHandler）可注入：默认 PipelineTaskHandler（D3 真实管线）；
- 取消：executor.cancel(task_id) 设置线程事件，处理链在检查点（progress.check_cancel）
  抛出 TaskCancelledError；取消后清理并保持 cancelled 状态。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Protocol

from app.config import WORKER_CONCURRENCY
from app.models import TaskStatus, now_iso
from app.services.task_event_bus import task_snapshot
from app.services.task_state import TaskStateError, assert_transition
from app.storage import db
from app.utils.logging import get_logger

logger = get_logger("executor")

PHASES = ("decode", "preprocess", "infer", "postprocess", "save")


class ProgressError(ValueError):
    """进度非法：超出 0~100 或发生回退。"""


class TaskCancelledError(Exception):
    """协作式取消：处理链在检查点检测到取消请求时抛出。"""


class ProgressReporter:
    """单个任务的进度上报器：0~100 单调递增、实时落库、阶段时间线与 SSE 发布。"""

    def __init__(
        self,
        task_id: int,
        *,
        cancel_event: threading.Event | None = None,
        event_bus: Any | None = None,
    ):
        self._task_id = task_id
        self._progress = 0
        self._cancel_event = cancel_event
        self._event_bus = event_bus
        self._active_phase: str | None = None
        self._active_phase_id: int | None = None
        self._active_phase_started: float | None = None

    @property
    def progress(self) -> int:
        return self._progress

    def check_cancel(self) -> None:
        """检查点：检测到取消请求（线程事件或 DB 状态）时抛出 TaskCancelledError。"""
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise TaskCancelledError(f"任务已取消（task_id={self._task_id}）")
        current = db.get_task(self._task_id)
        if current is not None and current["status"] == TaskStatus.CANCELLED:
            raise TaskCancelledError(f"任务已取消（task_id={self._task_id}）")

    def update(self, progress: int, phase: str) -> None:
        if not isinstance(progress, int) or not 0 <= progress <= 100:
            raise ProgressError(f"进度必须在 0~100 之间: {progress!r}")
        if progress < self._progress:
            raise ProgressError(f"进度不能回退: {self._progress} -> {progress}")
        if not phase:
            raise ProgressError("阶段 phase 不能为空")
        if phase != self._active_phase:
            self._finish_active_phase()
            self._start_phase(phase)
        db.update_task_progress(self._task_id, progress, phase)
        if self._event_bus is not None:
            task = db.get_task(self._task_id)
            if task is not None:
                self._event_bus.publish(self._task_id, task_snapshot(task))
        self._progress = progress

    def finalize(self) -> None:
        """关闭当前未结束的阶段日志（成功/失败/取消后由执行器调用）。"""
        self._finish_active_phase()

    def _start_phase(self, phase: str) -> None:
        self._active_phase = phase
        self._active_phase_started = time.monotonic()
        self._active_phase_id = db.log_phase_start(self._task_id, phase, now_iso())

    def _finish_active_phase(self) -> None:
        if self._active_phase_id is None:
            return
        duration_ms = int((time.monotonic() - self._active_phase_started) * 1000)
        db.log_phase_finish(self._active_phase_id, now_iso(), duration_ms)
        self._active_phase = None
        self._active_phase_id = None
        self._active_phase_started = None


class TaskHandler(Protocol):
    """任务处理器协议：D3 真实管线实现同一接口。"""

    def run(
        self,
        task_id: int,
        image_ids: list[int],
        params: dict[str, Any],
        progress: ProgressReporter,
    ) -> dict[str, Any]:
        """执行任务；成功返回 result，需在结束前上报 progress=100。"""
        ...


class TaskExecutor:
    """FIFO 任务队列执行器：固定数量 worker 线程消费队列。"""

    def __init__(
        self,
        concurrency: int | None = None,
        handler: TaskHandler | None = None,
        event_bus: Any | None = None,
    ):
        self._concurrency = max(1, concurrency if concurrency is not None else WORKER_CONCURRENCY)
        if handler is None:
            from app.services.pipeline_handler import PipelineTaskHandler

            handler = PipelineTaskHandler()
        self._handler = handler
        self._event_bus = event_bus
        self._queue: queue.Queue[int] = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._cancel_events: dict[int, threading.Event] = {}
        self._cancel_lock = threading.Lock()

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

    def cancel(self, task_id: int) -> None:
        """设置取消事件：处理链在下一个检查点中断（DB 状态由 service 层写入）。"""
        with self._cancel_lock:
            event = self._cancel_events.setdefault(task_id, threading.Event())
        event.set()

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
        # 条件迁移：仅当 DB 仍为 queued 时才置 processing，
        # 避免覆盖并发取消（queued 状态下取消）已写入的 cancelled
        if not db.update_task_status(
            task_id,
            TaskStatus.PROCESSING,
            started_at=now_iso(),
            expected_status=TaskStatus.QUEUED,
        ):
            return
        self._publish(task_id)
        reporter = ProgressReporter(
            task_id,
            cancel_event=self._cancel_events.get(task_id),
            event_bus=self._event_bus,
        )
        try:
            result = self._handler.run(task_id, task["image_ids"], task["params"], reporter)
            reporter.finalize()
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
            self._publish(task_id)
            self._close_bus(task_id)
            logger.info("任务成功 task_id=%s", task_id)
        except Exception as exc:  # noqa: BLE001 - 处理器异常统一转为 failed
            reporter.finalize()
            if self._is_cancelled(task_id):
                return
            if isinstance(exc, TaskCancelledError):
                # 兜底：取消事件已设置但 DB 尚未写入 cancelled（并发窗口），
                # 保持 cancelled 而不是误标 failed
                db.update_task_status(
                    task_id,
                    TaskStatus.CANCELLED,
                    finished_at=now_iso(),
                    expected_status=TaskStatus.PROCESSING,
                )
                self._publish(task_id)
                self._close_bus(task_id)
                logger.info("任务取消 task_id=%s（executor 兜底）", task_id)
                return
            try:
                assert_transition(TaskStatus.PROCESSING, TaskStatus.FAILED)
            except TaskStateError:
                return
            db.update_task_status(
                task_id, TaskStatus.FAILED, error=str(exc), finished_at=now_iso()
            )
            self._publish(task_id)
            self._close_bus(task_id)
            logger.error("任务失败 task_id=%s: %s", task_id, exc)
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(task_id, None)

    def _is_cancelled(self, task_id: int) -> bool:
        current = db.get_task(task_id)
        return current is not None and current["status"] == TaskStatus.CANCELLED

    def _publish(self, task_id: int) -> None:
        if self._event_bus is None:
            return
        task = db.get_task(task_id)
        if task is not None:
            self._event_bus.publish(task_id, task_snapshot(task))

    def _close_bus(self, task_id: int) -> None:
        if self._event_bus is not None:
            self._event_bus.close(task_id)
