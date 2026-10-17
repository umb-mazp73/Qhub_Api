from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.infrastructure.rate_limit.memory import MemoryRateLimiter

IdentityResolver = Callable[[Request], str | None]
NextHandler = Callable[[Request], Awaitable[Response]]

# Estos endpoints se llaman SIN token, así que el límite por cuenta no los alcanza: se
# frenan por IP (fuerza bruta de contraseñas, registros masivos).
AUTH_PATHS = frozenset({"/auth/token", "/auth/registro"})


def account_key_from_request(request: Request, validate_token) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        owner_type, owner_id = validate_token(authorization.split(" ", 1)[1])
    except HTTPException:
        return None
    value = getattr(owner_type, "value", owner_type)
    return f"{value}:{owner_id}"


def _too_many(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=429, content={"detail": detail}, headers={"Retry-After": "60"}
    )


def create_rate_limit_middleware(
    limiter: MemoryRateLimiter,
    requests_per_minute: int | Callable[[], int],
    identity_resolver: IdentityResolver,
    auth_requests_per_minute: int | Callable[[], int] = 0,
):
    def _value(setting: int | Callable[[], int]) -> int:
        return setting() if callable(setting) else setting

    async def middleware(request: Request, call_next: NextHandler) -> Response:
        if request.method == "POST" and request.url.path in AUTH_PATHS:
            auth_limit = _value(auth_requests_per_minute)
            client = request.client.host if request.client else "desconocido"
            if not limiter.allow(f"auth:{client}", auth_limit):
                return _too_many(
                    f"Demasiados intentos desde esta dirección ({auth_limit}/minuto). "
                    "Esperá un minuto."
                )

        limit = _value(requests_per_minute)
        account_key = identity_resolver(request)
        if account_key is not None and not limiter.allow(account_key, limit):
            return _too_many(
                f"Límite de {limit} requests/minuto excedido para esta cuenta"
            )
        return await call_next(request)

    return middleware
