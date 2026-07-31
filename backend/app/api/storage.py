"""磁盘占用统计与清理 API。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import config
from app.services import disk
from app.utils.errors import AppError

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/stats")
def storage_stats() -> dict:
    """按数量/体积统计原图目录（uploads）与输出目录（outputs）。"""
    return disk.get_storage_stats(config.UPLOADS_DIR, config.OUTPUTS_DIR)


class CleanupRequest(BaseModel):
    scope: str = Field(default="outputs", pattern="^(uploads|outputs|all)$")
    max_count: int | None = Field(default=None, ge=0)
    max_bytes: int | None = Field(default=None, ge=0)
    dry_run: bool = True


@router.post("/cleanup")
def cleanup_storage(body: CleanupRequest) -> dict:
    """按数量上限/体积上限计算可删项并（可选）实际删除；默认 dry_run 只计算不删除。"""
    if body.max_count is None and body.max_bytes is None:
        raise AppError("cleanup_requires_limit", "至少提供 max_count 或 max_bytes 之一")
    targets = (
        [config.UPLOADS_DIR, config.OUTPUTS_DIR]
        if body.scope == "all"
        else [config.UPLOADS_DIR if body.scope == "uploads" else config.OUTPUTS_DIR]
    )
    planned: list[disk.FileEntry] = []
    for directory in targets:
        planned.extend(disk.plan_cleanup(disk.scan_directory(directory), body.max_count, body.max_bytes))
    if not body.dry_run:
        for entry in planned:
            entry.path.unlink(missing_ok=True)
    return {
        "dry_run": body.dry_run,
        "scope": body.scope,
        "count": len(planned),
        "freed_bytes": sum(entry.size_bytes for entry in planned),
        "deleted": [str(entry.path) for entry in planned],
    }