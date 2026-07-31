"""健康检查 API。"""
from __future__ import annotations

from fastapi import APIRouter

from app.config import PROJECT_ROOT
from app.services import settings as settings_svc
from app.storage import db

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health() -> dict:
    try:
        db.get_setting("ping", "pong")
        storage_ok = True
    except Exception:  # noqa: BLE001 - 健康检查需兜底任何存储异常
        storage_ok = False
    return {
        "status": "ok" if storage_ok else "degraded",
        "name": "PhotoRestore",
        "version": _read_version(),
        "storage": "ok" if storage_ok else "error",
        "capabilities": settings_svc.get_capabilities(),
    }


def _read_version() -> str:
    try:
        return (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
