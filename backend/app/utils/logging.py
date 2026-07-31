"""日志配置（loguru）。"""
from __future__ import annotations

import sys

from loguru import logger

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    )
    logger.add("logs/photorestore.log", rotation="10 MB", retention=7, level="DEBUG", encoding="utf-8")
    _configured = True


def get_logger(name: str):
    setup_logging()
    return logger.bind(module=name)
