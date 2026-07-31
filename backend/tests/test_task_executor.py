"""执行器/服务测试：并发上限、进度单调、重启恢复、参数指纹、取消（全部 hermetic）。"""
from __future__ import annotations

import threading
import time

import pytest

from app.models import TaskStatus, now_iso
from app.services import tasks as tasks_svc
from app.services.executor import ProgressError, ProgressReporter, TaskExecutor
from app.services.task_state import TaskStateError
from app.storage import db


@pytest.fixture()
def db_ready():
    db.init_db()
    db.wipe_data()
    yield


def _make_image() -> int:
    return db.create_image(filename="a.jpg", size_bytes=100, format_="jpg", path="/tmp/a.jpg")


def _make_task(params: dict | None = None) -> int:
    image_id = _make_image()
    return tasks_svc.create_task([image_id], "restore", params or {"scale": 2})


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


class BlockingHandler:
    """可门控的处理器：started 表示首个任务开始执行，release 放行。"""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def run(self, task_id, image_ids, params, progress):
        with self._lock:
            self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("handler 未在预期时间内被释放")
        progress.update(100, "save")
        return {"ok": True}


def test_concurrency_1_only_one_processing(db_ready):
    handler = BlockingHandler()
    executor = TaskExecutor(concurrency=1, handler=handler)
    executor.start()
    try:
        task1 = _make_task()
        task2 = _make_task()
        executor.enqueue(task1)
        executor.enqueue(task2)
        assert handler.started.wait(timeout=2)
        time.sleep(0.2)
        assert db.get_task(task1)["status"] == TaskStatus.PROCESSING
        assert db.get_task(task2)["status"] == TaskStatus.QUEUED
        handler.release.set()
        _wait_until(
            lambda: db.get_task(task1)["status"] == TaskStatus.SUCCEEDED
            and db.get_task(task2)["status"] == TaskStatus.SUCCEEDED
        )
    finally:
        handler.release.set()
        executor.stop()


def test_concurrency_2_allows_two_processing(db_ready):
    handler = BlockingHandler()
    executor = TaskExecutor(concurrency=2, handler=handler)
    executor.start()
    try:
        task1 = _make_task()
        task2 = _make_task()
        executor.enqueue(task1)
        executor.enqueue(task2)
        _wait_until(lambda: handler.calls == 2)
        assert db.get_task(task1)["status"] == TaskStatus.PROCESSING
        assert db.get_task(task2)["status"] == TaskStatus.PROCESSING
        handler.release.set()
        _wait_until(
            lambda: db.get_task(task1)["status"] == TaskStatus.SUCCEEDED
            and db.get_task(task2)["status"] == TaskStatus.SUCCEEDED
        )
    finally:
        handler.release.set()
        executor.stop()


def test_progress_rollback_fails_task(db_ready):
    class BadHandler:
        def run(self, task_id, image_ids, params, progress):
            progress.update(10, "decode")
            progress.update(50, "infer")
            progress.update(30, "infer")  # 回退 → ProgressError，任务应失败
            return {"ok": True}

    executor = TaskExecutor(concurrency=1, handler=BadHandler())
    executor.start()
    try:
        task_id = _make_task()
        executor.enqueue(task_id)
        _wait_until(lambda: db.get_task(task_id)["status"] == TaskStatus.FAILED)
        task = db.get_task(task_id)
        assert "进度不能回退" in task["error"]
        assert task["progress"] == 50  # 最后一次合法落库值
        assert task["finished_at"]
    finally:
        executor.stop()


def test_progress_persisted_and_success(db_ready):
    log: list[tuple[int, str]] = []

    class GoodHandler:
        def run(self, task_id, image_ids, params, progress):
            for value, phase in [(10, "decode"), (40, "preprocess"), (80, "infer"), (100, "save")]:
                progress.update(value, phase)
                log.append((value, phase))
            return {"ok": True, "task_id": task_id}

    executor = TaskExecutor(concurrency=1, handler=GoodHandler())
    executor.start()
    try:
        task_id = _make_task()
        executor.enqueue(task_id)
        _wait_until(lambda: db.get_task(task_id)["status"] == TaskStatus.SUCCEEDED)
        task = db.get_task(task_id)
        assert task["progress"] == 100
        assert task["phase"] == "save"
        assert task["result"] == {"ok": True, "task_id": task_id}
        assert task["started_at"] and task["finished_at"]
        assert log == [(10, "decode"), (40, "preprocess"), (80, "infer"), (100, "save")]
    finally:
        executor.stop()


def test_progress_reporter_rejects_invalid_values(db_ready):
    task_id = _make_task()
    reporter = ProgressReporter(task_id)
    with pytest.raises(ProgressError):
        reporter.update(-1, "decode")
    with pytest.raises(ProgressError):
        reporter.update(101, "decode")
    with pytest.raises(ProgressError):
        reporter.update(10, "")


def test_restart_recovery_marks_processing_failed(db_ready):
    processing_id = _make_task()
    db.update_task_status(processing_id, TaskStatus.PROCESSING, started_at=now_iso())
    queued_id = _make_task()
    succeeded_id = _make_task()
    db.update_task_status(succeeded_id, TaskStatus.PROCESSING, started_at=now_iso())
    db.update_task_status(succeeded_id, TaskStatus.SUCCEEDED, progress=100, finished_at=now_iso())

    count = tasks_svc.recover_interrupted_tasks()

    assert count == 1
    processing = db.get_task(processing_id)
    assert processing["status"] == TaskStatus.FAILED
    assert "restart" in processing["error"]
    assert db.get_task(queued_id)["status"] == TaskStatus.QUEUED
    assert db.get_task(succeeded_id)["status"] == TaskStatus.SUCCEEDED


def test_params_hash_deterministic():
    assert tasks_svc.compute_params_hash({"a": 1, "b": [2]}) == tasks_svc.compute_params_hash(
        {"b": [2], "a": 1}
    )
    assert tasks_svc.compute_params_hash({"a": 1}) != tasks_svc.compute_params_hash({"a": 2})
    assert len(tasks_svc.compute_params_hash({"a": 1})) == 64


def test_cancel_queued_task(db_ready):
    task_id = _make_task()
    result = tasks_svc.cancel_task(task_id)
    assert result["status"] == TaskStatus.CANCELLED
    assert result["finished_at"]


def test_cancel_processing_task(db_ready):
    task_id = _make_task()
    db.update_task_status(task_id, TaskStatus.PROCESSING, started_at=now_iso())
    result = tasks_svc.cancel_task(task_id)
    assert result["status"] == TaskStatus.CANCELLED
    assert result["finished_at"]


def test_cancel_succeeded_rejected(db_ready):
    task_id = _make_task()
    db.update_task_status(task_id, TaskStatus.PROCESSING, started_at=now_iso())
    db.update_task_status(task_id, TaskStatus.SUCCEEDED, progress=100, finished_at=now_iso())
    with pytest.raises(TaskStateError):
        tasks_svc.cancel_task(task_id)


def test_executor_skips_cancelled_task(db_ready):
    handler = BlockingHandler()
    executor = TaskExecutor(concurrency=1, handler=handler)
    executor.start()
    try:
        task_id = _make_task()
        tasks_svc.cancel_task(task_id)
        executor.enqueue(task_id)
        time.sleep(0.3)
        assert db.get_task(task_id)["status"] == TaskStatus.CANCELLED
        assert handler.calls == 0
    finally:
        handler.release.set()
        executor.stop()