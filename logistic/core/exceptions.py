"""
Makosa ya mfumo (business errors) na jinsi yanavyorudishwa kwa app.

Kila kosa linarudi kama JSON: {"detail": "ujumbe"} - app inasoma `detail`.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class BadRequest(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND


class Conflict(AppError):
    # App ya zamani inapokea 400 kwa "tayari ipo" - tunabaki hivyo.
    status_code = status.HTTP_400_BAD_REQUEST


class PermissionDenied(AppError):
    # App inatambua 406 kama "huna ruhusa".
    status_code = status.HTTP_406_NOT_ACCEPTABLE


class PaymentRequired(AppError):
    # 402: subscription ya kampuni imeisha (au moduli haipo kwenye mpango wake) - app inaonyesha ukurasa wa kulipia.
    status_code = status.HTTP_402_PAYMENT_REQUIRED


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        parts.append(f"{field}: {err.get('msg')}" if field else str(err.get("msg")))
    return "; ".join(parts) or "Invalid request"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            content={"detail": _validation_message(exc)})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            content={"detail": f"An exception occurred: {exc}"})
