"""模型元数据 API：任务类型 / 引擎 / 文件就绪状态与体积（D8）。"""
from __future__ import annotations

from fastapi import APIRouter

from app.services import model_registry

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def list_models() -> dict:
    """返回模型清单（就绪状态 / 缺失文件 / 体积）与缺模型时的下载指引。"""
    return model_registry.get_model_status()
