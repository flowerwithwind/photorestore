"""统一异常与错误响应格式。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务异常：由统一处理器转为 JSON 响应。"""

    def __init__(self, code: str, message: str, status_code: int = 400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=_error_body("validation_error", "请求参数校验失败", exc.errors()))

    @app.exception_handler(404)
    async def not_found_handler(_request: Request, _exc: Exception):
        return JSONResponse(status_code=404, content=_error_body("not_found", "接口不存在"))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception):
        return JSONResponse(status_code=500, content=_error_body("internal_error", f"服务器内部错误: {exc}"))
