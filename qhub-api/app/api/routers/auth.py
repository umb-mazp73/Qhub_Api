from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response

from app.api.core.security import get_cuenta_opcional, get_cuenta_requerida
from app.application.errors import ApplicationError
from app.domain.models import (
    ChangePassword,
    LoginCommand,
    RegisterAccount,
    RequestPasswordReset,
    ResetPassword,
)
from app.application.use_cases.auth import AuthUseCases
from app.domain.enums import PropietarioTipo
from app.api.core.deps import (
    get_auth_use_cases,
    http_error,
    owner_from_claims,
)
from app.api.schemas.auth import (
    ApiKeyEstado,
    ApiKeyGenerar,
    ApiKeyNueva,
    CambiarClaveCrear,
    LoginCrear,
    MensajeOut,
    RecuperarCrear,
    RegistroCrear,
    RegistroOut,
    RestablecerCrear,
    TokenOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/registro", response_model=RegistroOut, status_code=201)
async def registrar(
    datos: RegistroCrear,
    cuenta_actual: dict | None = Depends(get_cuenta_opcional),
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Registro self-service de una cuenta que va a consumir la API.

    Tres casos, todos por el mismo endpoint:

    1. tipo_cuenta="empresa" SIN sesión → crea la entidad `empresas` y su primera
       cuenta en `control_empresas`, atómicamente (RPC registrar_empresa).
    2. tipo_cuenta="empresa" CON sesión → NO crea una empresa nueva: agrega otra cuenta
       a la empresa del access_token. El empresa_id sale del token firmado, nunca del
       body, así que es imposible engancharse a una empresa ajena. No hace falta ningún
       rol (esta API no gestiona roles): alcanza con haber iniciado sesión en ella.
    3. tipo_cuenta="usuario" → crea una cuenta individual en `usuarios` (RPC
       registrar_usuario). Una cuenta de usuario es dueña de sí misma, así que acá no
       aplica el caso de "sumar una cuenta más".

    Después de registrarse, el login es POST /auth/token con email o nombre_usuario +
    password."""
    command = RegisterAccount(
        tipo_cuenta=PropietarioTipo(datos.tipo_cuenta),
        nombre_empresa=datos.nombre_empresa,
        nombre=datos.nombre,
        apellido=datos.apellido,
        nombre_usuario=datos.nombre_usuario,
        email=str(datos.email),
        password=datos.password,
        pais=datos.pais,
        ciudad=datos.ciudad,
        acepto_terminos=datos.acepto_terminos,
    )
    try:
        result = await casos.register(command, owner_from_claims(cuenta_actual))
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return RegistroOut(
        propietario_tipo=result.owner.tipo,
        propietario_id=result.owner.id,
        nombre_usuario=result.nombre_usuario,
        email=result.email,
        nombre_empresa=result.nombre_empresa,
        limite_colas=result.limite_colas,
        creada_en=result.creada_en,
    )


@router.post("/token", response_model=TokenOut)
async def crear_access_token(
    datos: LoginCrear | None = None,
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Login obligatorio: paso previo requerido antes de poder usar cualquier otro
    endpoint de la API. Funciona igual para los dos tipos de cuenta (empresa o usuario);
    dos formas de identificarse, cualquiera de las dos (no ambas a la vez):

      1. Body JSON {identificador, password} — cuenta creada en POST /auth/registro.
         `identificador` puede ser el nombre_usuario o el email, case-insensitive.
      2. Header X-Api-Key — para empresas dadas de alta por un admin de la plataforma
         (POST /empresas), o para cualquier cuenta a la que se le haya emitido una key.

    En ambos casos se devuelve el mismo access_token (JWT propio, corta duración) para
    usar en Authorization: Bearer. Es OPCIONAL: los endpoints de negocio también aceptan
    la api key directa (X-Api-Key o Authorization: Bearer <api key>), así que quien integra
    puede saltarse este paso. La password cruda solo se acepta aquí."""
    command = LoginCommand(
        identificador=datos.identificador if datos else None,
        password=datos.password if datos else None,
        api_key=x_api_key,
    )
    try:
        token = await casos.login(command)
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return TokenOut(access_token=token.value, expires_in=token.expires_in_seconds)


@router.get("/api-key", response_model=ApiKeyEstado)
async def estado_api_key(
    cuenta: dict = Depends(get_cuenta_requerida),
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Si la cuenta tiene una api key activa y desde cuándo. Nunca devuelve la llave."""
    info = await casos.api_key_info(owner_from_claims(cuenta))
    return ApiKeyEstado(activa=info.activa, creada_en=info.creada_en)


@router.post("/api-key", response_model=ApiKeyNueva, status_code=201)
async def emitir_api_key(
    datos: ApiKeyGenerar,
    cuenta: dict = Depends(get_cuenta_requerida),
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Emite la api key permanente de la cuenta (o la rota, si ya tenía una).

    La api key NO vence: se cambia por un access_token con POST /auth/token (header
    X-Api-Key) las veces que haga falta, y deja de valer solo cuando se rota o se revoca.
    Se muestra una única vez en esta respuesta. Requiere el access_token de la cuenta y
    confirmar la contraseña. Los access_token ya emitidos siguen valiendo hasta que
    expiren (la rotación los respeta: duran minutos, no son la credencial permanente)."""
    try:
        issued = await casos.issue_api_key(
            owner_from_claims(cuenta), datos.identificador, datos.password
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return ApiKeyNueva(api_key=issued.api_key, creada_en=issued.creada_en)


@router.delete("/api-key", status_code=204)
async def revocar_api_key(
    cuenta: dict = Depends(get_cuenta_requerida),
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Revoca la api key de la cuenta: deja de servir para POST /auth/token."""
    await casos.revoke_api_key(owner_from_claims(cuenta))
    return Response(status_code=204)


@router.post("/recuperar", response_model=MensajeOut)
async def recuperar(
    datos: RecuperarCrear,
    background: BackgroundTasks,
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Pide un enlace para restablecer la contraseña. Responde SIEMPRE el mismo texto
    exista o no el correo (anti-enumeración); el envío corre después de responder."""
    try:
        job = await casos.request_password_reset(
            RequestPasswordReset(email=str(datos.email))
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc
    if job is not None:
        background.add_task(casos.send_reset_email, job)
    return MensajeOut(
        detail="Si el correo está registrado, te enviamos un enlace para restablecer la contraseña."
    )


@router.post("/restablecer", response_model=MensajeOut)
async def restablecer(
    datos: RestablecerCrear,
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Fija la contraseña nueva usando el token del enlace. 401 si el token no es válido
    o expiró."""
    try:
        await casos.reset_password(
            ResetPassword(token=datos.token, new_password=datos.password)
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return MensajeOut(
        detail="Tu contraseña se actualizó. Ya puedes iniciar sesión con la nueva."
    )


@router.post("/cambiar-clave", response_model=MensajeOut)
async def cambiar_clave(
    datos: CambiarClaveCrear,
    casos: AuthUseCases = Depends(get_auth_use_cases),
):
    """Cambia la contraseña identificándose con la actual. 401 si las credenciales no valen."""
    try:
        await casos.change_password(
            ChangePassword(
                identificador=datos.identificador,
                current_password=datos.password_actual,
                new_password=datos.password_nueva,
            )
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return MensajeOut(detail="Tu contraseña se actualizó.")
