"""内存事件总线：任务快照 pub/sub，供 SSE 推送（D4）。

约定：
- publish 永不带锁阻塞：无订阅者时仅缓冲（deque maxlen），不影响执行线程；
- 每个任务缓冲最近 maxlen 条事件，断线重连可补发；
- 任务终态后由执行器/服务调用 close()，SSE 消费完剩余事件后发 done 并断开。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from app.models import now_iso


def task_snapshot(task: dict[str, Any] | None) -> dict[str, Any]:
    """把任务记录压缩为 SSE 快照字段（D5 前端契约）。"""
    task = task or {}
    return {
        "task_id": task.get("id"),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "progress": task.get("progress", 0),
        "phase": task.get("phase"),
        "params_hash": task.get("params_hash"),
        "error": task.get("error"),
        "result": task.get("result"),
        "ts": now_iso(),
    }


class TaskEventBus:
    """每任务一个环形缓冲 + 条件变量；poll 供 SSE 生成器阻塞取事件。"""

    def __init__(self, maxlen: int = 200):
        self._maxlen = maxlen
        self._events: dict[int, deque[tuple[int, dict[str, Any]]]] = {}
        self._seqs: dict[int, int] = {}
        self._closed: set[int] = set()
        self._conds: dict[int, threading.Condition] = {}
        self._lock = threading.Lock()

    def publish(self, task_id: int, event: dict[str, Any]) -> None:
        """发布一条快照事件；无订阅者时仅入缓冲，不阻塞调用方。"""
        with self._lock:
            seq = self._seqs.get(task_id, 0) + 1
            self._seqs[task_id] = seq
            payload = dict(event)
            payload["seq"] = seq
            self._events.setdefault(task_id, deque(maxlen=self._maxlen)).append((seq, payload))
            cond = self._conds.get(task_id)
        if cond is not None:
            with cond:
                cond.notify_all()

    def latest_seq(self, task_id: int) -> int:
        """返回任务当前已发布的最大 seq（无事件时为 0），供 SSE 初始快照补 seq。"""
        with self._lock:
            return self._seqs.get(task_id, 0)

    def close(self, task_id: int) -> None:
        """标记任务事件流关闭（终态后调用）。"""
        with self._lock:
            self._closed.add(task_id)
            cond = self._conds.get(task_id)
        if cond is not None:
            with cond:
                cond.notify_all()

    def poll(
        self,
        task_id: int,
        after_seq: int = 0,
        timeout: float = 15.0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """阻塞等待新事件；返回 (新增事件列表, 是否已关闭)。超时返回空列表。"""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            cond = self._conds.setdefault(task_id, threading.Condition())
        with cond:
            while True:
                with self._lock:
                    events = self._events.get(task_id, ())
                    new = [payload for seq, payload in events if seq > after_seq]
                    closed = task_id in self._closed
                if new or closed:
                    return new, closed
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return [], closed
                cond.wait(remaining)
