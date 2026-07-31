"""任务 API：入队、详情、列表、取消、SSE 进度推送、产物下载（D4）。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.models import TaskCreate, TaskStatus, now_iso
from app.services import tasks as tasks_svc
from app.services.task_event_bus import task_snapshot
from app.services.task_state import TERMINAL_STATUSES
from app.storage import db
from app.utils.errors import AppError

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_MEDIA_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _sse(event: str, data: dict[str, Any]) -> str:
    """序列化一条 SSE 帧：event + data（UTF-8 JSON）+ 空行。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("", status_code=201)
def create_task(body: TaskCreate, request: Request) -> dict:
    """创建任务并入队，立即返回 task_id + status=queued。"""
    task_id = tasks_svc.create_task(body.image_ids, body.task_type.value, body.params)
    executor = getattr(request.app.state, "executor", None)
    if executor is not None:
        executor.enqueue(task_id)
    return {"task_id": task_id, "status": TaskStatus.QUEUED.value}


@router.get("")
def list_tasks(
    status: TaskStatus | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    items = tasks_svc.list_tasks(status=status.value if status else None, limit=limit, offset=offset)
    return {"items": items, "total": len(items)}


@router.get("/{task_id}")
def get_task(task_id: int) -> dict:
    """任务详情：状态、进度（0~100）、阶段、参数、阶段时间线与结果（含产物）。"""
    return tasks_svc.get_task_detail(task_id)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: int, request: Request) -> dict:
    """取消任务：queued 直接取消；processing 协作式中断（检查点清理并标记 cancelled）。"""
    executor = getattr(request.app.state, "executor", None)
    event_bus = getattr(request.app.state, "event_bus", None)
    return tasks_svc.cancel_task(task_id, executor=executor, event_bus=event_bus)


@router.get("/{task_id}/events")
async def stream_task_events(task_id: int, request: Request) -> StreamingResponse:
    """SSE 事件流（EventSource 可用）：snapshot/update/done + 心跳注释行。

    事件 data 为任务快照：task_id/task_type/status/progress/phase/params_hash/error/result/ts。
    客户端断开不影响任务执行；终态后推送 done 并关闭连接；轮询详情接口不受影响。
    """
    task = db.get_task(task_id)
    if task is None:
        raise AppError("task_not_found", "任务不存在", status_code=404)
    event_bus = getattr(request.app.state, "event_bus", None)
    if event_bus is None:
        raise AppError("events_unavailable", "事件总线未启用", status_code=503)
    return StreamingResponse(
        _event_stream(task_id, event_bus),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(task_id: int, event_bus: Any):
    task = db.get_task(task_id)
    yield _sse("snapshot", task_snapshot(task))
    if task is not None and task["status"] in TERMINAL_STATUSES:
        # 已终态：补发缓冲事件后立即 done（含并发订阅前已完成的任务）
        events, _ = await asyncio.to_thread(event_bus.poll, task_id, 0, 0.2)
        for event in events:
            yield _sse("update", event)
        yield _sse("done", {"task_id": task_id, "ts": now_iso()})
        return
    last_seq = 0
    while True:
        events, closed = await asyncio.to_thread(event_bus.poll, task_id, last_seq, 15.0)
        for event in events:
            last_seq = max(last_seq, int(event.get("seq", 0)))
            yield _sse("update", event)
        if closed:
            yield _sse("done", {"task_id": task_id, "ts": now_iso()})
            break
        yield ": ping\n\n"


@router.get("/{task_id}/outputs/{index}/download")
def download_output(task_id: int, index: int) -> FileResponse:
    """下载任务产物（按 result.outputs 下标定位），供前端展示/下载。"""
    task = tasks_svc.get_task_detail(task_id)
    outputs = (task.get("result") or {}).get("outputs") or []
    if not 0 <= index < len(outputs):
        raise AppError("output_not_found", "产物不存在", status_code=404)
    entry = outputs[index]
    path = Path(entry["path"])
    if not path.is_file():
        raise AppError("output_file_missing", f"产物文件缺失: {path}", status_code=404)
    media_type = _MEDIA_TYPES.get(str(entry.get("format", "")), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=str(entry.get("filename", path.name)))
