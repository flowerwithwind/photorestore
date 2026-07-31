"""任务 API：入队、详情、列表、取消。"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.models import TaskCreate, TaskStatus
from app.services import tasks as tasks_svc

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
    """任务详情：状态、进度（0~100）、阶段 phase、参数、错误与结果。"""
    return tasks_svc.get_task_detail(task_id)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: int) -> dict:
    """取消任务（仅 queued 状态可取消）。"""
    return tasks_svc.cancel_task(task_id)