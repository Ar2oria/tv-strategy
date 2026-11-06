"""Composition-root error responses with distinct API and non-API behavior."""

import logging
from collections.abc import Mapping
from http import HTTPStatus

from app.api.responses import error_response
from app.config.store import ConfigApplyError
from app.static_frontend import frontend_index
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)
API_PREFIX = "/api/"
API_ERROR_MESSAGES = {
    400: "Bad request",
    404: "Resource not found",
    405: "Method not allowed",
    413: "Request is too large",
    429: "Too many requests",
    500: "An internal error occurred",
}


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith(API_PREFIX)


def public_error_response(
    path: str,
    *,
    code: str,
    message: str,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Use the public envelope only for API paths, never exception internals."""
    if is_api_path(path):
        return error_response(
            code,
            message,
            status_code,
            headers=headers,
        )
    return JSONResponse(
        status_code=status_code,
        content={"detail": message},
        headers=dict(headers or {}),
    )


def register_application_error_handlers(app: FastAPI) -> None:
    """Override generic handlers with route-aware sanitized composition errors."""

    async def config_apply_failed(
        request: Request, error: ConfigApplyError
    ) -> JSONResponse:
        logger.error(
            "Configuration apply failed for %s",
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return public_error_response(
            request.url.path,
            code="configuration_apply_failed",
            message="Configuration could not be applied",
            status_code=500,
        )

    async def http_error(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        if error.status_code == 404 and not is_api_path(request.url.path):
            spa = frontend_index(request)
            if spa is not None:
                return spa  # type: ignore[return-value]
        api = is_api_path(request.url.path)
        message = (
            API_ERROR_MESSAGES.get(error.status_code, "Request failed")
            if api
            else _non_api_message(error.status_code)
        )
        return public_error_response(
            request.url.path,
            code="http_error",
            message=message,
            status_code=error.status_code,
            headers=error.headers,
        )

    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled application error for %s",
            request.url.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return public_error_response(
            request.url.path,
            code="internal_error",
            message=(
                _non_api_message(500)
                if not is_api_path(request.url.path)
                else API_ERROR_MESSAGES[500]
            ),
            status_code=500,
        )

    app.add_exception_handler(ConfigApplyError, config_apply_failed)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error)


def _non_api_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"
