from fastapi import HTTPException

from app.config.config import settings
from app.application.errors import CryptoFailure, Unauthorized
from app.infrastructure.security.jwt_tokens import verify_token


async def resolver_token_websocket(token: str) -> dict:
    partes = token.split(":", 2)
    if len(partes) < 2:
        raise HTTPException(
            401, "Token de WS inválido, formato esperado access_token:usuario_id[:rol]"
        )
    access_token, usuario_id = partes[0], partes[1]
    rol = partes[2] if len(partes) > 2 else None
    try:
        propietario_tipo, propietario_id = verify_token(
            settings.JWT_SECRET_KEY, access_token
        )
    except CryptoFailure as exc:
        raise HTTPException(500, "JWT_SECRET_KEY no está configurada") from exc
    except Unauthorized as exc:
        raise HTTPException(401, exc.detail) from exc
    if not usuario_id:
        raise HTTPException(401, "usuario_id requerido en el token de WS")
    return {
        "usuario_id": usuario_id,
        "rol": rol or "cliente",
        "email": None,
        "propietario_tipo": propietario_tipo,
        "propietario_id": propietario_id,
    }
