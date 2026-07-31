"""PhotoRestore FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, images
from app.api import models as models_api
from app.api import settings as settings_api
from app.api import storage as storage_api
from app.api import tasks as tasks_api
from app.config import ensure_dirs
from app.services import tasks as tasks_svc
from app.services.executor import TaskExecutor
from app.services.pipeline_handler import PipelineTaskHandler
from app.services.task_event_bus import TaskEventBus
from app.storage import db
from app.utils.errors import register_exception_handlers
from app.utils.logging import get_logger, setup_logging

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    ensure_dirs()
    db.init_db()
    # 重启恢复：遗留 processing 任务标记为 failed（原因 restart）
    tasks_svc.recover_interrupted_tasks()
    # 事件总线：SSE 进度推送（无订阅者时纯缓冲，不阻塞执行）
    app.state.event_bus = TaskEventBus()
    # 启动线程池执行器（并发默认 1，PHOTORESTORE_CONCURRENCY 可配；D4 使用真实管线处理器）
    app.state.executor = TaskExecutor(
        handler=PipelineTaskHandler(),
        event_bus=app.state.event_bus,
    )
    app.state.executor.start()
    logger.info("PhotoRestore 启动完成")
    try:
        yield
    finally:
        app.state.executor.stop()
        logger.info("PhotoRestore 已停止")


app = FastAPI(
    title="PhotoRestore API",
    description="AI 影像修复工作台后端（本地模型 / 经典算法保底）",
    version="1.0.0-dev",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(health.router)
app.include_router(images.router)
app.include_router(models_api.router)
app.include_router(settings_api.router)
app.include_router(tasks_api.router)
app.include_router(storage_api.router)