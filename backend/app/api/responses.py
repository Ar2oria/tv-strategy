"""Consistent API envelopes and sanitized exception mappings."""

import logging
from collections.abc import Mapping
from typing import Any

from app.config.store import ConfigConflictError, ConfigValidationError
from app.repositories.task_runs import TaskRunNotFoundError
from app.services.bar_service import InstrumentNotFoundError
from app.services.indicator_service import IndicatorRequestError
from app.services.task_runner import TaskParameterError
from app.services.task_service import InvalidTaskConfigError
from app.tasks.registry import UnknownTaskError
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

HTTP_ERROR_MESSAGES = {
    400: "Bad request",
    404: "Resource not found",
    405: "Method not allowed",
    413: "Request is too large",
    429: "Too many requests",
}


def success_response(
    data: Any,
    *,
    meta: Mapping[str, Any] | None = None,
    status_code: int = 200,
) -> JSONResponse:
    """Serialize DTOs and dates inside the public success envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": jsonable_encoder(data),
            "error": None,
            "meta": dict(meta or {}),
        },
    )


def error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    meta: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return a stable error object without exception details or tracebacks."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": {"code": code, "message": message},
            "meta": dict(meta or {}),
        },
        headers=dict(headers or {}),
    )


def register_response_handlers(app: FastAPI) -> None:
    """Install read-API handlers on an isolated app or the composition root."""

    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        logger.info("Request validation failed for %s", request.url.path)
        return error_response("validation_error", "Request validation failed", 422)

    async def instrument_not_found(
        request: Request, error: InstrumentNotFoundError
    ) -> JSONResponse:
        return error_response("instrument_not_found", "Instrument not found", 404)

    async def invalid_indicator_request(
        request: Request, error: IndicatorRequestError
    ) -> JSONResponse:
        return error_response(error.code, str(error), 422)

    async def unknown_task(request: Request, error: UnknownTaskError) -> JSONResponse:
        return error_response("task_not_found", "Task not found", 404)

    async def unknown_task_run(
        request: Request, error: TaskRunNotFoundError
    ) -> JSONResponse:
        return error_response("task_run_not_found", "Task run not found", 404)

    async def invalid_task_params(
        request: Request, error: TaskParameterError
    ) -> JSONResponse:
        return error_response("invalid_task_params", "Invalid task parameters", 422)

    async def invalid_task_config(
        request: Request, error: InvalidTaskConfigError
    ) -> JSONResponse:
        return error_response("invalid_task_config", "Invalid task configuration", 422)

    async def invalid_config(
        request: Request, error: ConfigValidationError
    ) -> JSONResponse:
        return error_response("invalid_configuration", "Invalid configuration", 422)

    async def config_conflict(
        request: Request, error: ConfigConflictError
    ) -> JSONResponse:
        return error_response("config_conflict", "Configuration revision conflict", 409)

    async def http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        message = HTTP_ERROR_MESSAGES.get(error.status_code, "Request failed")
        return error_response("http_error", message, error.status_code)

    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled API error for %s",
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return error_response("internal_error", "An internal error occurred", 500)

    app.add_exception_handler(RequestValidationError, validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(InstrumentNotFoundError, instrument_not_found)  # type: ignore[arg-type]
    app.add_exception_handler(IndicatorRequestError, invalid_indicator_request)  # type: ignore[arg-type]
    app.add_exception_handler(UnknownTaskError, unknown_task)  # type: ignore[arg-type]
    app.add_exception_handler(TaskRunNotFoundError, unknown_task_run)  # type: ignore[arg-type]
    app.add_exception_handler(TaskParameterError, invalid_task_params)  # type: ignore[arg-type]
    app.add_exception_handler(InvalidTaskConfigError, invalid_task_config)  # type: ignore[arg-type]
    app.add_exception_handler(ConfigValidationError, invalid_config)  # type: ignore[arg-type]
    app.add_exception_handler(ConfigConflictError, config_conflict)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error)
