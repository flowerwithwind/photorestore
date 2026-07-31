"""图像服务层：解码、EXIF 方向归一、预处理缩放、RGB 转换与后处理编码。

管线内部约定：
- 解码与后处理使用 Pillow，中间表示统一为 RGB HWC uint8 numpy 数组；
- 超大图先等比缩放到 max_dimension 内，避免推理内存峰值；
- 尺寸与体积全程记录（ImageMetrics），供 D4 落库与磁盘统计复用。

支持输出格式：jpeg / png / webp / bmp / tiff（jpeg、webp 可调 quality）。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import MAX_IMAGE_DIMENSION, OUTPUT_QUALITY

# 输出格式别名 -> Pillow 格式名
_OUTPUT_FORMATS: dict[str, str] = {
    "jpeg": "JPEG",
    "jpg": "JPEG",
    "png": "PNG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "tif": "TIFF",
}


class ImageDecodeError(ValueError):
    """图像解码失败（数据损坏或不支持的格式）。"""


class ImageEncodeError(ValueError):
    """图像编码失败（不支持的输出格式或非法参数）。"""


@dataclass(frozen=True)
class ImageMetrics:
    """管线尺寸与体积记录：输入（解码前）与输出（编码后）对比。"""

    input_format: str | None
    input_size_bytes: int
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    output_format: str
    output_size_bytes: int


def decode_image(data: bytes) -> Image.Image:
    """从字节解码为 PIL 图像（已强制加载像素，失败抛 ImageDecodeError）。"""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImageDecodeError("输入图像数据为空或类型非法")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDecodeError(f"无法解码图像: {exc}") from exc


def normalize_exif_orientation(image: Image.Image) -> Image.Image:
    """EXIF Orientation 归一：按 EXIF 旋转使图像正向显示；无 EXIF 时原样返回。"""
    return ImageOps.exif_transpose(image)


def limit_max_dimension(
    image: Image.Image,
    max_dimension: int = MAX_IMAGE_DIMENSION,
) -> Image.Image:
    """等比缩放使最长边不超过 max_dimension；已达标时原样返回。"""
    if max_dimension <= 0:
        raise ValueError(f"max_dimension 必须为正数: {max_dimension!r}")
    width, height = image.size
    longest = max(width, height)
    if longest <= max_dimension:
        return image
    scale = max_dimension / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def to_rgb_array(image: Image.Image) -> np.ndarray:
    """任意 PIL 模式转 RGB HWC uint8；RGBA 先合成到白底。"""
    if image.mode == "RGB":
        rgb = image
    elif image.mode == "RGBA":
        rgb = Image.new("RGB", image.size, (255, 255, 255))
        rgb.paste(image, mask=image.split()[3])
    else:
        rgb = image.convert("RGB")
    return np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))


def preprocess_image(
    data: bytes,
    max_dimension: int = MAX_IMAGE_DIMENSION,
) -> tuple[np.ndarray, ImageMetrics]:
    """解码 + EXIF 归一 + 缩放 + RGB 转换，返回 (rgb, 输入侧指标)。"""
    image = decode_image(data)
    input_format = (image.format or "unknown").lower()
    input_width, input_height = image.size
    normalized = normalize_exif_orientation(image)
    resized = limit_max_dimension(normalized, max_dimension)
    rgb = to_rgb_array(resized)
    height, width = rgb.shape[:2]
    metrics = ImageMetrics(
        input_format=input_format,
        input_size_bytes=len(data),
        input_width=input_width,
        input_height=input_height,
        output_width=width,
        output_height=height,
        output_format="",
        output_size_bytes=0,
    )
    return rgb, metrics


def encode_image(
    rgb: np.ndarray,
    output_format: str = "jpeg",
    quality: int = OUTPUT_QUALITY,
) -> bytes:
    """RGB HWC uint8 -> 编码字节；format 控制容器，quality 控制有损压缩强度。"""
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ImageEncodeError(f"输入必须是 HWC 三通道数组: {rgb.shape}")
    if rgb.dtype != np.uint8:
        raise ImageEncodeError(f"输入必须是 uint8: {rgb.dtype}")
    canonical = output_format.lower().lstrip(".")
    pillow_format = _OUTPUT_FORMATS.get(canonical)
    if pillow_format is None:
        raise ImageEncodeError(
            f"不支持的输出格式: {output_format}（可选: {sorted(_OUTPUT_FORMATS)}）"
        )
    if not 1 <= quality <= 100:
        raise ImageEncodeError(f"quality 必须在 1~100 之间: {quality!r}")
    image = Image.fromarray(rgb, mode="RGB")
    buffer = io.BytesIO()
    save_kwargs: dict[str, object] = {"format": pillow_format}
    if pillow_format == "JPEG" or pillow_format == "WEBP":
        save_kwargs["quality"] = quality
    elif pillow_format == "PNG":
        save_kwargs["compress_level"] = 6
    try:
        image.save(buffer, **save_kwargs)
    except (OSError, ValueError) as exc:
        raise ImageEncodeError(f"图像编码失败: {exc}") from exc
    return buffer.getvalue()


def postprocess_array(
    rgb: np.ndarray,
    output_format: str = "jpeg",
    quality: int = OUTPUT_QUALITY,
) -> tuple[bytes, str]:
    """后处理编码：返回 (字节, 规范格式名)，jpg 统一归一为 jpeg。"""
    canonical = output_format.lower().lstrip(".")
    canonical = "jpeg" if canonical == "jpg" else canonical
    data = encode_image(rgb, canonical, quality)
    return data, canonical
