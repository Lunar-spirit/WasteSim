from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _envelope(code: str, message: str, details: Any, request_id: str) -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        # jsonable_encoder, not exc.errors() directly: a custom validator
        # (e.g. a Pydantic model_validator) that raises a bare ValueError
        # produces an error dict whose "ctx" holds the original exception
        # object, which plain json.dumps cannot serialize and would crash
        # this handler with a 500 instead of the 400 it is trying to return.
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_envelope(
                "VALIDATION_ERROR", "Request body failed validation", jsonable_encoder(exc.errors()), request_id
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("HTTP_ERROR", str(exc.detail), None, request_id),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("INTERNAL_ERROR", "An unexpected error occurred", None, request_id),
        )
