import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.application.errors import (
    ApplicationError,
    BadRequest,
    BrokerUnavailable,
    Conflict,
    CryptoFailure,
    Forbidden,
    NotFound,
    PersistenceFailure,
    PersistenceUnavailable,
    TooManyRequests,
    Unauthorized,
    UnprocessableInput,
)

logger = logging.getLogger("qhub_api.presentation.errors")

STATUS_BY_TYPE: dict[type[ApplicationError], int] = {
    BadRequest: 400,
    UnprocessableInput: 422,
    Conflict: 409,
    NotFound: 404,
    Unauthorized: 401,
    Forbidden: 403,
    TooManyRequests: 429,
    PersistenceUnavailable: 500,
    PersistenceFailure: 500,
    BrokerUnavailable: 500,
    CryptoFailure: 500,
}


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    status = STATUS_BY_TYPE.get(type(exc), 500)
    headers = None
    if isinstance(exc, TooManyRequests):
        headers = {"Retry-After": str(exc.retry_after_seconds)}
    if status == 500:
        logger.error("Fallo interno en %s: %s", request.url.path, exc.kind)
    return JSONResponse(status_code=status, content={"detail": exc.detail}, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
