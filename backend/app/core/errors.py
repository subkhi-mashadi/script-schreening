"""Error terstruktur: semua kesalahan API berbentuk {"error": {"code", "message", "details"}}."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(what: str = "Data") -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"{what} tidak ditemukan.")


def forbidden() -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, "FORBIDDEN", "Anda tidak memiliki izin untuk tindakan ini.")


def unauthorized(message: str = "Sesi tidak valid atau sudah berakhir. Silakan login kembali.") -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", message)


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            _body("VALIDATION_ERROR", "Data yang dikirim tidak valid. Periksa kolom yang ditandai.", {"errors": errors}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("HTTP_ERROR", str(exc.detail)), status_code=exc.status_code)
