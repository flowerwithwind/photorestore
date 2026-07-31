"""图像元数据 API。

D2 先登记元数据（供任务入队引用）；D3 实现真实文件上传后复用同一入口。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import config
from app.storage import db
from app.utils.errors import AppError

router = APIRouter(prefix="/api/images", tags=["images"])


class ImageCreate(BaseModel):
    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    format: str
    path: str | None = None


@router.post("", status_code=201)
def create_image(body: ImageCreate) -> dict:
    fmt = body.format.lower().lstrip(".")
    if fmt not in config.ALLOWED_EXTENSIONS:
        raise AppError(
            "unsupported_format",
            f"不支持的图像格式: {body.format}",
            details={"allowed": sorted(config.ALLOWED_EXTENSIONS)},
        )
    path = body.path or str(config.UPLOADS_DIR / body.filename)
    image_id = db.create_image(
        filename=body.filename,
        size_bytes=body.size_bytes,
        format_=fmt,
        path=path,
    )
    return db.get_image(image_id)


@router.get("/{image_id}")
def get_image(image_id: int) -> dict:
    image = db.get_image(image_id)
    if image is None:
        raise AppError("image_not_found", "图像不存在", status_code=404)
    return image