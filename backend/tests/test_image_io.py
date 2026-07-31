"""图像服务层测试：EXIF 归一 / 缩放 / RGB 转换 / 后处理编码与体积记录（hermetic）。"""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.services import image_io

EXIF_ORIENTATION_TAG = 0x0112


def _solid_png(width: int = 16, height: int = 12) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 40, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_with_orientation(width: int, height: int, orientation: int) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (width, height), (200, 30, 40))
    exif = Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = orientation
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_preprocess_records_input_metrics():
    rgb, metrics = image_io.preprocess_image(_solid_png())
    assert rgb.shape == (12, 16, 3)
    assert rgb.dtype == np.uint8
    assert metrics.input_format == "png"
    assert metrics.input_size_bytes > 0
    assert (metrics.input_width, metrics.input_height) == (16, 12)
    assert (metrics.output_width, metrics.output_height) == (16, 12)
    assert metrics.output_size_bytes == 0


def test_decode_invalid_bytes_raises():
    with pytest.raises(image_io.ImageDecodeError):
        image_io.decode_image(b"not-an-image")


def test_decode_empty_bytes_raises():
    with pytest.raises(image_io.ImageDecodeError):
        image_io.decode_image(b"")


def test_exif_orientation_normalized():
    data = _jpeg_with_orientation(20, 10, 6)
    rgb, metrics = image_io.preprocess_image(data)
    assert rgb.shape == (20, 10, 3)  # 旋转后宽高互换
    assert (metrics.input_width, metrics.input_height) == (20, 10)
    assert (metrics.output_width, metrics.output_height) == (10, 20)


def test_limit_max_dimension_scales_down():
    image = Image.new("RGB", (200, 100))
    resized = image_io.limit_max_dimension(image, max_dimension=100)
    assert resized.size == (100, 50)


def test_limit_max_dimension_keeps_small_image():
    image = Image.new("RGB", (64, 48))
    assert image_io.limit_max_dimension(image, max_dimension=100) is image


def test_limit_max_dimension_rejects_non_positive():
    with pytest.raises(ValueError):
        image_io.limit_max_dimension(Image.new("RGB", (10, 10)), max_dimension=0)


@pytest.mark.parametrize(
    ("mode", "color"),
    [
        ("L", (128,)),
        ("RGBA", (10, 20, 30, 0)),
        ("P", (5,)),
    ],
)
def test_to_rgb_array_converts_any_mode(mode, color):
    image = Image.new(mode, (8, 6), color)
    rgb = image_io.to_rgb_array(image)
    assert rgb.shape == (6, 8, 3)
    assert rgb.dtype == np.uint8


def test_to_rgb_array_rgba_composites_on_white():
    image = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    rgb = image_io.to_rgb_array(image)
    assert tuple(rgb[0, 0]) == (255, 255, 255)


def test_encode_jpeg_quality_controls_size():
    rng = np.random.default_rng(42)
    rgb = rng.integers(0, 256, size=(48, 48, 3), dtype=np.uint8)
    low = image_io.encode_image(rgb, "jpeg", quality=10)
    high = image_io.encode_image(rgb, "jpeg", quality=95)
    assert len(high) > len(low)


def test_encode_png_magic_and_unsupported_format():
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    data = image_io.encode_image(rgb, "png")
    assert data.startswith(b"\x89PNG")
    with pytest.raises(image_io.ImageEncodeError):
        image_io.encode_image(rgb, "gif")
    with pytest.raises(image_io.ImageEncodeError):
        image_io.encode_image(rgb, "jpeg", quality=101)


def test_encode_image_validates_input():
    with pytest.raises(image_io.ImageEncodeError):
        image_io.encode_image(np.zeros((8, 8), dtype=np.uint8), "jpeg")
    with pytest.raises(image_io.ImageEncodeError):
        image_io.encode_image(np.zeros((8, 8, 3), dtype=np.float32), "jpeg")


def test_postprocess_array_normalizes_format_name():
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    data, canonical = image_io.postprocess_array(rgb, "jpg")
    assert canonical == "jpeg"
    assert data.startswith(b"\xff\xd8")
