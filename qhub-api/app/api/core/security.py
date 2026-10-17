import secrets

from fastapi import Depends, Header, HTTPException

from app.config.config import settings
from app.domain.enums import PropietarioTipo
from app.application.errors import CryptoFailure, Unauthorized
from app.infrastructure.security.jwt_tokens import verify_token

# El login es POST /auth/token (ver routers/auth.py): cambia la credencial de la cuenta (api
# key, o email/usuario + password) por un access_token de corta duración firmado por
# nosotros. Es el ÚNICO mecanismo de auth: la credencial cruda NUNCA se acepta fuera de ese
# login, así ningún cliente puede "saltarse" el inicio de sesión.
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


# --- Punto único que usan todos los routers de negocio ---
async def get_current_user(
    authorization: str | None = Header(None),
    x_usuario_id: str | None = Header(None, alias="X-Usuario-Id"),
    x_usuario_rol: str | None = Header(None, alias="X-Usuario-Rol"),
) -> dict:
    """Requiere sesión iniciada: Authorization: Bearer <access_token> obtenido en
    POST /auth/token. No acepta la api key ni la password crudas — solo son válidas en
    el login. Si no hay token o es inválido/expirado, 401 con instrucción de loguearse.

    Devuelve la identidad de la cuenta (propietario_tipo/propietario_id, del token
    firmado) más la del usuario final del sistema externo (usuario_id/rol, de los
    headers). Qhub-api no gestiona usuarios finales: solo lee lo que el sistema externo
    informa sobre su propio usuario."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            401,
            "No hay sesión iniciada. Iniciá sesión con POST /auth/token "
            "(con X-Api-Key o {identificador, password})",
        )

    propietario_tipo, propietario_id = _validar_access_token_propio(authorization.split(" ", 1)[1])

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
    """Identidad de la cuenta cuando la sesión es OPCIONAL, sin exigir X-Usuario-Id.

    La usa POST /auth/registro para distinguir sus dos casos con un solo endpoint:
      * sin Authorization → crea la empresa Y su primera cuenta
      * con Authorization → crea SOLO una cuenta más, dentro de la empresa del token
    De esa forma una empresa ya registrada nunca se duplica, y el permiso para sumar
    una cuenta lo da el propio token (haber iniciado sesión en esa empresa) — no hace
    falta ningún rol, que es algo que esta API deliberadamente no gestiona."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    propietario_tipo, propietario_id = _validar_access_token_propio(authorization.split(" ", 1)[1])
    return {"propietario_tipo": propietario_tipo, "propietario_id": propietario_id}


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
