"""Application error hierarchy and consistent JSON error handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Expected error that maps to the shared error body."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.headers = headers or {}


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Please start a new session."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "That action is not allowed."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "We could not find that."


class InvalidInputError(AppError):
    status_code = 422
    code = "invalid_input"
    message = "Please try that again."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Please wait a moment and try again."

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after)})


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Please try again in a moment."


class InternalError(AppError):
    status_code = 500
    code = "internal_error"
    message = "Something went wrong."


_STATUS_CODES: dict[int, str] = {
    400: "invalid_input",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_input",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

_MESSAGES: dict[str, str] = {
    "not_found": "We could not find that.",
    "unauthorized": "Please start a new session.",
    "forbidden": "That action is not allowed.",
    "rate_limited": "Please wait a moment and try again.",
    "service_unavailable": "Please try again in a moment.",
}


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def _with_request_id(response: JSONResponse, request: Request) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _with_request_id(
        JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message),
            headers=exc.headers,
        ),
        request,
    )


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _with_request_id(
        JSONResponse(
            status_code=422,
            content=error_body("invalid_input", "Please try that again."),
        ),
        request,
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    default_code = "internal_error" if status >= 500 else "invalid_input"
    code = _STATUS_CODES.get(status, default_code)
    message = _MESSAGES.get(code, "Please try that again.")
    headers: dict[str, str] = {}
    if exc.headers:
        headers.update(
            {key: value for key, value in exc.headers.items() if key.lower() == "retry-after"}
        )
    return _with_request_id(
        JSONResponse(status_code=status, content=error_body(code, message), headers=headers),
        request,
    )


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("unhandled_error", extra={"request_id": request_id, "status": 500})
    return _with_request_id(
        JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong."),
        ),
        request,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
