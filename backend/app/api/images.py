"""图片元数据 API。

D2 先登记元数据（供任务入队引用）；D6 扩展为画廊服务：
列表（含任务摘要/产物）、原图下载、演示种子图片、级联删除（图片+任务+产物）；
D10 增加真实字节上传（multipart /api/images/upload）。
"""
from __future__ import annotations

import base64
import binascii
import io
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from app import config
from app.storage import db
from app.utils.errors import AppError

router = APIRouter(prefix="/api/images", tags=["images"])

_MEDIA_TYPES = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
}


class ImageCreate(BaseModel):
    filename: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    format: str
    path: str | None = None


class SeedImage(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1)


@router.post("", status_code=201)
def create_image(body: ImageCreate) -> dict:
    fmt = body.format.lower().lstrip(".")
    if fmt not in config.ALLOWED_EXTENSIONS:
        raise AppError(
            "unsupported_format",
            f"不支持的图片格式: {body.format}",
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


@router.post("/upload", status_code=201)
async def upload_image(file: Annotated[UploadFile, File()]) -> dict:
    """真实字节上传（D10）：multipart 文件 → 扩展名/大小/PIL 内容校验 → 规范化落盘并登记。

    - 扩展名不在 ALLOWED_EXTENSIONS → 400 unsupported_format；
    - 字节数超过 MAX_UPLOAD_BYTES → 413 image_too_large（边读边限，不整块载入内存）；
    - 内容无法解码（非图片/损坏）→ 400 invalid_image；
    - 超大尺寸图片由管线等比缩放到 MAX_IMAGE_DIMENSION 内（不拒绝，记录原始尺寸）。
    """
    original = Path(file.filename or "").name
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in config.ALLOWED_EXTENSIONS:
        raise AppError(
            "unsupported_format",
            f"不支持的图片格式: {original or '(无文件名)'}",
            details={"allowed": sorted(config.ALLOWED_EXTENSIONS)},
        )
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise AppError(
                "image_too_large",
                f"图片超过大小限制 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB",
                status_code=413,
                details={"max_bytes": config.MAX_UPLOAD_BYTES},
            )
    if not data:
        raise AppError("empty_image", "图片数据为空", status_code=400)
    return _normalize_and_register(bytes(data), original, prefix="upload")


@router.get("")
def list_images(
    task_type: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """画廊列表：图片 + 关联任务摘要（含产物 download_url），可按任务类型/状态筛选。"""
    if task_type is not None and task_type not in config.SUPPORTED_TASK_TYPES:
        raise AppError(
            "unsupported_task_type",
            f"不支持的任务类型: {task_type}",
            details={"allowed": sorted(config.SUPPORTED_TASK_TYPES)},
        )
    return db.list_images_with_tasks(
        task_type=task_type,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/seed", status_code=201)
def seed_image(body: SeedImage) -> dict:
    """演示种子图片：Base64 JSON 上传，PIL 校验后规范化写入 uploads/ 并登记。"""
    try:
        raw = base64.b64decode(body.data_base64, validate=True)
    except (ValueError, binascii.Error):
        raise AppError("invalid_base64", "图片数据不是合法的 Base64", status_code=400)
    if not raw:
        raise AppError("empty_image", "图片数据为空", status_code=400)
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise AppError(
            "image_too_large",
            f"图片超过大小限制 {config.MAX_UPLOAD_BYTES // 1024 // 1024}MB",
            status_code=413,
            details={"max_bytes": config.MAX_UPLOAD_BYTES},
        )
    return _normalize_and_register(raw, body.filename, prefix="seed")


def _normalize_and_register(data: bytes, filename: str, *, prefix: str = "upload") -> dict:
    """PIL 校验 + RGB 规范化后写入 uploads/ 并登记，返回图片记录（seed 与 upload 共用）。"""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "jpeg").lower()
            if fmt == "jpg":
                fmt = "jpeg"
            if fmt not in config.ALLOWED_EXTENSIONS:
                raise AppError(
                    "unsupported_format",
                    f"不支持的图片格式: {fmt}",
                    details={"allowed": sorted(config.ALLOWED_EXTENSIONS)},
                )
            normalized = img.convert("RGB")
            buffer = io.BytesIO()
            normalized.save(buffer, format="JPEG" if fmt == "jpeg" else fmt.upper())
            payload = buffer.getvalue()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - PIL 解码失败统一转业务错误
        raise AppError("invalid_image", f"图片内容无法解码: {exc}", status_code=400)
    safe_name = Path(filename).name or "image.jpg"
    unique_name = f"{prefix}_{uuid.uuid4().hex[:8]}_{safe_name}"
    target = config.UPLOADS_DIR / unique_name
    target.write_bytes(payload)
    image_id = db.create_image(
        filename=unique_name,
        size_bytes=len(payload),
        format_=fmt,
        path=str(target),
    )
    return db.get_image(image_id)


@router.get("/{image_id}")
def get_image(image_id: int) -> dict:
    image = db.get_image(image_id)
    if image is None:
        raise AppError("image_not_found", "图片不存在", status_code=404)
    return image


@router.get("/{image_id}/download")
def download_image(image_id: int) -> FileResponse:
    """下载原图（画廊缩略图/对比组件用），文件名经 Content-Disposition 下发。"""
    image = _require_image(image_id)
    path = Path(image["path"])
    if not path.is_file():
        raise AppError("file_not_found", "原图文件不存在（可能已被清理）", status_code=404)
    media_type = _MEDIA_TYPES.get(image["format"], "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=image["filename"])


@router.delete("/{image_id}")
def delete_image(image_id: int) -> dict:
    """删除图片：级联删除关联任务记录与产物文件（引用完整性由单事务保证）。"""
    image = _require_image(image_id)
    deleted = db.delete_image_cascade(image_id)
    if deleted is None:  # 并发删除时行已消失
        raise AppError("image_not_found", "图片不存在", status_code=404)
    removed: list[str] = []
    paths: list[str] = [image["path"], *deleted["output_paths"]]
    for raw in paths:
        try:
            Path(raw).unlink(missing_ok=True)
            removed.append(raw)
        except OSError:
            continue
    return {
        "deleted": True,
        "image_id": image_id,
        "deleted_task_ids": deleted["task_ids"],
        "removed_files": removed,
    }


def _require_image(image_id: int) -> dict[str, Any]:
    image = db.get_image(image_id)
    if image is None:
        raise AppError("image_not_found", "图片不存在", status_code=404)
    return image
