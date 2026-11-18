import secrets

from fastapi import Depends, Header, HTTPException, Request

from app.config.config import settings
from app.domain.enums import PropietarioTipo
from app.application.errors import CryptoFailure, Unauthorized
from app.infrastructure.security.jwt_tokens import verify_token

# Hay dos credenciales válidas en los endpoints de negocio: la API KEY de la cuenta (no vence,
# directa en cada petición) o un access_token de corta duración que se obtiene con
# POST /auth/token (api key, o email/usuario + password). La PASSWORD cruda solo se acepta en
# ese login. Gestionar la api key (y sumar cuentas con login a una empresa) exige un
# access_token: una api key filtrada no puede crear otras credenciales.
#
# La identidad de la cuenta viaja siempre como el par (propietario_tipo, propietario_id),
# firmado dentro del token: un id de empresa y uno de usuario podrían coincidir, así que el
# tipo nunca se infiere.


def _validar_access_token_propio(token: str) -> tuple[PropietarioTipo, str]:
    try:
        return verify_token(settings.JWT_SECRET_KEY, token)
    except CryptoFailure as exc:
        raise HTTPException(500, "JWT_SECRET_KEY no está configurada") from exc
    except Unauthorized as exc:
        raise HTTPException(401, exc.detail) from exc


def es_jwt(token: str) -> bool:
    """Un JWT tiene tres segmentos separados por puntos; una api key (token_urlsafe) no tiene puntos."""
    return token.count(".") == 2


def api_key_de_la_peticion(authorization: str | None, x_api_key: str | None) -> str | None:
    """La api key viaja en `X-Api-Key` o como `Authorization: Bearer <api key>`; un Bearer con
    forma de JWT no es una api key. None si la petición no trae api key."""
    if x_api_key:
        return x_api_key
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        if token and not es_jwt(token):
            return token
    return None


async def cuenta_por_api_key(container, api_key: str) -> tuple[PropietarioTipo, str]:
    owner = await container.auth.authenticate_api_key(api_key)
    if owner is None:
        raise HTTPException(401, "API key inválida o revocada")
    return owner.tipo, str(owner.id)


# --- Punto único que usan todos los routers de negocio ---
async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    x_usuario_id: str | None = Header(None, alias="X-Usuario-Id"),
    x_usuario_rol: str | None = Header(None, alias="X-Usuario-Rol"),
) -> dict:
    """Requiere credencial de la cuenta, de una de estas formas:

      * la API KEY directa (no vence): `X-Api-Key: <api key>` o `Authorization: Bearer <api key>`
      * un access_token de corta duración: `Authorization: Bearer <jwt>` (POST /auth/token)

    Con la api key el desarrollador no necesita pedir tokens: la manda en cada petición.
    La password cruda NUNCA se acepta aquí (solo en POST /auth/token).

    Devuelve la identidad de la cuenta (propietario_tipo/propietario_id) más la del usuario
    final del sistema externo (usuario_id/rol, de los headers). Qhub-api no gestiona
    usuarios finales: solo lee lo que el sistema externo informa sobre su propio usuario."""
    api_key = api_key_de_la_peticion(authorization, x_api_key)
    if api_key is not None:
        propietario_tipo, propietario_id = await cuenta_por_api_key(
            request.app.state.container, api_key
        )
    elif authorization and authorization.startswith("Bearer "):
        propietario_tipo, propietario_id = _validar_access_token_propio(
            authorization.split(" ", 1)[1]
        )
    else:
        raise HTTPException(
            401,
            "Falta la credencial. Enviá tu API key (header X-Api-Key o "
            "Authorization: Bearer <api key>) o un access_token de POST /auth/token",
        )

    if not x_usuario_id:
        raise HTTPException(401, "X-Usuario-Id requerido")

    return {
        "usuario_id": x_usuario_id,
        "rol": x_usuario_rol or "cliente",
        "email": None,
        "propietario_tipo": propietario_tipo,
        "propietario_id": propietario_id,
    }


async def get_cuenta_opcional(authorization: str | None = Header(None)) -> dict | None:
    """Identidad de la cuenta cuando la sesión es OPCIONAL, sin exigir X-Usuario-Id. Solo
    acepta un access_token (sesión): la api key no sirve para sumar cuentas con login a una
    empresa ni para gestionar la propia api key.

    La usa POST /auth/registro para distinguir sus dos casos con un solo endpoint:
      * sin Authorization → crea la empresa Y su primera cuenta
      * con Authorization → crea SOLO una cuenta más, dentro de la empresa del token
    De esa forma una empresa ya registrada nunca se duplica, y el permiso para sumar
    una cuenta lo da el propio token (haber iniciado sesión en esa empresa) — no hace
    falta ningún rol, que es algo que esta API deliberadamente no gestiona."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    if not es_jwt(authorization.split(" ", 1)[1]):
        raise HTTPException(
            401, "Esta operación requiere un access_token (POST /auth/token), no la api key"
        )

    propietario_tipo, propietario_id = _validar_access_token_propio(authorization.split(" ", 1)[1])
    return {"propietario_tipo": propietario_tipo, "propietario_id": propietario_id}


async def get_cuenta_requerida(authorization: str | None = Header(None)) -> dict:
    """Cuenta del token, SIN exigir X-Usuario-Id: para gestionar la propia cuenta (su api
    key), que no es una operación de negocio sobre colas o turnos."""
    cuenta = await get_cuenta_opcional(authorization)
    if cuenta is None:
        raise HTTPException(
            401,
            "No hay sesión iniciada. Iniciá sesión con POST /auth/token "
            "(con X-Api-Key o {identificador, password})",
        )
    return cuenta


def requerir_rol(*roles_permitidos: str):
    def dependencia(usuario: dict = Depends(get_current_user)) -> dict:
        if usuario["rol"] not in roles_permitidos:
            raise HTTPException(403, f"Requiere uno de estos roles: {', '.join(roles_permitidos)}")
        return usuario

    return dependencia


def verificar_admin(x_admin_api_key: str | None = Header(None, alias="X-Admin-Api-Key")) -> None:
    """Protege app/api/routers/empresas.py — administración de la plataforma, no un rol de usuario."""
    if not settings.ADMIN_API_KEY or not x_admin_api_key or not secrets.compare_digest(
        x_admin_api_key, settings.ADMIN_API_KEY
    ):
        raise HTTPException(401, "ADMIN_API_KEY inválida")
