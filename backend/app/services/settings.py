"""能力上报与全局设置服务。"""
from __future__ import annotations

from app.config import MAX_UPLOAD_BYTES, MODEL_META, WORKER_CONCURRENCY


def get_capabilities() -> dict:
    """返回前端可用的能力描述（用于演示模式标识与功能开关）。"""
    return {
        "llm": False,  # PhotoRestore 无 LLM 依赖，全本地处理
        "demo_mode": True,
        "engine": "classic+onnx",
        "model_count": len(MODEL_META),
        "task_types": list(MODEL_META),
        "models": {
            key: {
                "name": meta["name"],
                "files": list(meta["files"]),
                "required": bool(meta["required"]),
                "engine": meta["engine"],
            }
            for key, meta in MODEL_META.items()
        },
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "worker_concurrency": WORKER_CONCURRENCY,
    }
