from fastapi import APIRouter, BackgroundTasks, Depends, Header

from app.api.core.security import get_cuenta_opcional
from app.application.errors import ApplicationError
from app.domain.models import (
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
    usar en Authorization: Bearer en el resto de los endpoints. Este endpoint es el
    ÚNICO lugar donde se acepta la api key o la password crudas — get_current_user()
    las rechaza en cualquier otro endpoint."""
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
