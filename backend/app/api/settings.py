"""设置 API：并发任务数配置（读取 PHOTORESTORE_CONCURRENCY 或 settings 表，可保存，D8）。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import config
from app.storage import db

router = APIRouter(prefix="/api/settings", tags=["settings"])

_SETTINGS_KEY = "worker_concurrency"


def _effective_concurrency() -> tuple[int, str]:
    """已保存配置优先，否则回退环境变量（进程启动时读取）。"""
    saved = db.get_setting(_SETTINGS_KEY)
    if isinstance(saved, int) and not isinstance(saved, bool) and saved >= 1:
        return saved, "db"
    return config.WORKER_CONCURRENCY, "env"


@router.get("")
def get_settings() -> dict:
    """读取并发数：settings 表已保存则优先，否则回退 PHOTORESTORE_CONCURRENCY。"""
    value, source = _effective_concurrency()
    return {
        "worker_concurrency": value,
        "source": source,
        "persisted": db.get_setting(_SETTINGS_KEY),
        "max_upload_bytes": config.MAX_UPLOAD_BYTES,
    }


class SaveSettingsRequest(BaseModel):
    worker_concurrency: int = Field(ge=1, le=64, description="并发任务数（1~64）")


@router.post("")
def save_settings(body: SaveSettingsRequest) -> dict:
    """保存并发数到 settings 表（持久化配置；执行器在启动时读取，重启后端后生效）。"""
    db.set_setting(_SETTINGS_KEY, body.worker_concurrency)
    return {
        "worker_concurrency": body.worker_concurrency,
        "saved": True,
        "note": "已保存到配置，重启后端后生效",
    }
