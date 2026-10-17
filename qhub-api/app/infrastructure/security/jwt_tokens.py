from datetime import datetime, timedelta, timezone

from jose import ExpiredSignatureError, JWTError, jwt

from app.application.errors import CryptoFailure, Unauthorized
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import AccessToken, OwnerId

ALGORITHM = "HS256"
ISSUER = "qhub-api"


class JwtAccessTokenService:
    def __init__(self, secret: str, expire_minutes: int = 60) -> None:
        self._secret = secret
        self._expire_minutes = expire_minutes

    def issue(self, owner: OwnerId) -> AccessToken:
        token, seconds = issue_token(
            self._secret, self._expire_minutes, owner.tipo, str(owner.id)
        )
        return AccessToken(token, seconds)

    def verify(self, token: str) -> OwnerId:
        from uuid import UUID

        owner_type, owner_id = verify_token(self._secret, token)
        try:
            return OwnerId(owner_type, UUID(owner_id))
        except ValueError as exc:
            raise Unauthorized("Access token con propietario_id inválido", "invalid") from exc


def issue_token(
    secret: str,
    expire_minutes: int,
    owner_type: PropietarioTipo | str,
    owner_id: str,
) -> tuple[str, int]:
    if not secret:
        raise CryptoFailure(operation="token_issue")
    expires_in = expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "propietario_tipo": PropietarioTipo(owner_type).value,
        "propietario_id": str(owner_id),
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    try:
        return jwt.encode(payload, secret, algorithm=ALGORITHM), expires_in
    except Exception as exc:
        raise CryptoFailure(operation="token_issue") from exc


def verify_token(secret: str, token: str) -> tuple[PropietarioTipo, str]:
    if not secret:
        raise CryptoFailure(operation="token_verify")
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM], issuer=ISSUER)
    except ExpiredSignatureError as exc:
        raise Unauthorized(
            "Access token expirado, pedí uno nuevo con POST /auth/token", "expired"
        ) from exc
    except JWTError as exc:
        raise Unauthorized(
            "Access token inválido, iniciá sesión con POST /auth/token", "invalid"
        ) from exc

    owner_type = payload.get("propietario_tipo")
    owner_id = payload.get("propietario_id")
    if not owner_type or not owner_id:
        raise Unauthorized(
            "Access token sin identidad de cuenta (propietario_tipo/propietario_id)",
            "invalid",
        )
    try:
        return PropietarioTipo(owner_type), str(owner_id)
    except ValueError as exc:
        raise Unauthorized("Access token con propietario_tipo inválido", "invalid") from exc
