"""PhotoRestore 全局配置：路径、上传限制与模型元信息集中于此。"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 数据目录（测试通过 PHOTORESTORE_DATA_DIR 重定向）
DATA_DIR = Path(os.environ.get("PHOTORESTORE_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "photorestore.db"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
TMP_DIR = DATA_DIR / "tmp"
MODELS_DIR = Path(os.environ.get("PHOTORESTORE_MODELS_DIR", PROJECT_ROOT / "models"))

# 上传与图像限制
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "bmp", "webp", "tiff", "tif"}
MAX_UPLOAD_BYTES = int(os.environ.get("PHOTORESTORE_MAX_UPLOAD_MB", "20")) * 1024 * 1024
MAX_IMAGE_DIMENSION = 8000
OUTPUT_QUALITY = 92

# 任务执行器（并发默认 1，避免 CPU 争抢）
WORKER_CONCURRENCY = int(os.environ.get("PHOTORESTORE_CONCURRENCY", "1"))
TASK_TIMEOUT_SECONDS = int(os.environ.get("PHOTORESTORE_TASK_TIMEOUT", "300"))

# 模型注册表元信息（D3 细化：文件清单 + 是否必需 + 引擎说明）
MODEL_META: dict[str, dict] = {
    "restore": {
        "key": "restore",
        "name": "去噪去模糊",
        "engine": "classic+realesrgan",
        "files": ["realesrgan-x4.onnx"],
        "required": False,
        "description": "OpenCV 经典算法保底（fastNlMeansDenoising + 维纳去模糊），可选 Real-ESRGAN",
    },
    "upscale": {
        "key": "upscale",
        "name": "超分辨率",
        "engine": "realesrgan",
        "files": ["realesrgan-x2.onnx", "realesrgan-x4.onnx"],
        "required": True,
        "description": "Real-ESRGAN ONNX ×2/×4",
    },
    "colorize": {
        "key": "colorize",
        "name": "黑白上色",
        "engine": "ddcolor",
        "files": ["ddcolor.onnx"],
        "required": True,
        "description": "DDColor ONNX（或等价替代模型）",
    },
}
SUPPORTED_TASK_TYPES: tuple[str, ...] = tuple(MODEL_META)


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR, TMP_DIR, MODELS_DIR):
        d.mkdir(parents=True, exist_ok=True)
