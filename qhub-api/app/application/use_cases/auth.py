import secrets
from datetime import timedelta

from app.application.errors import (
    ApplicationError,
    Conflict,
    Forbidden,
    Unauthorized,
    UnprocessableInput,
)
from app.domain.models import (
    LoginCommand,
    RegisterAccount,
    RegistrationDraft,
    RegistrationResult,
    RequestPasswordReset,
    ResetPassword,
)
from app.domain.interfaces.accounts import AccountRepository
from app.domain.interfaces.clock import Clock
from app.domain.interfaces.email import EmailSender
from app.domain.interfaces.security import ApiKeyCodec, AccessTokenService, PasswordHasher
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import AccessToken, EmailJob, OwnerId
from app.infrastructure.delivery.templates.password_reset_email import (
    PASSWORD_RESET_SUBJECT,
    password_reset_html,
)


_DUPLICATE = "El email o el nombre de usuario ya están registrados"
_USER_OWNER_FORBIDDEN = (
    "Estás usando el token de una cuenta de tipo usuario: una cuenta individual "
    "no puede tener cuentas adicionales. Registrate sin Authorization para crear "
    "una cuenta nueva."
)


class AuthUseCases:
    def __init__(
        self,
        accounts: AccountRepository,
        passwords: PasswordHasher,
        api_keys: ApiKeyCodec,
        tokens: AccessTokenService,
        clock: Clock,
        emails: EmailSender,
        reset_url: str,
        reset_ttl_minutos: int,
    ) -> None:
        self._accounts = accounts
        self._passwords = passwords
        self._api_keys = api_keys
        self._tokens = tokens
        self._clock = clock
        self._emails = emails
        self._reset_url = reset_url
        self._reset_ttl_minutos = reset_ttl_minutos
        self._dummy_hash: str | None = None

    async def register(
        self, command: RegisterAccount, current_owner: OwnerId | None
    ) -> RegistrationResult:
        username_norm = command.nombre_usuario.strip().lower()
        email_norm = command.email.strip().lower()
        if await self._accounts.identifier_exists(username_norm, email_norm):
            raise Conflict(_DUPLICATE)

        if command.tipo_cuenta is PropietarioTipo.EMPRESA and current_owner is not None:
            if current_owner.tipo is PropietarioTipo.USUARIO:
                raise Forbidden(_USER_OWNER_FORBIDDEN)
        if command.tipo_cuenta is PropietarioTipo.EMPRESA and current_owner is None:
            if not command.nombre_empresa:
                raise UnprocessableInput(
                    "nombre_empresa es obligatorio para registrar una empresa nueva"
                )
        if command.tipo_cuenta is PropietarioTipo.USUARIO:
            current_owner = None

        password_hash = await self._passwords.hash_password(command.password)
        draft = RegistrationDraft(
            tipo_cuenta=command.tipo_cuenta,
            owner=current_owner,
            nombre_empresa=command.nombre_empresa,
            nombre=command.nombre,
            apellido=command.apellido,
            nombre_usuario=command.nombre_usuario,
            email=str(command.email),
            password_hash=password_hash,
            pais=command.pais,
            ciudad=command.ciudad,
            acepto_terminos_en=self._clock.now_utc(),
        )
        return await self._accounts.register(draft)

    async def authenticate_api_key(self, api_key: str) -> OwnerId | None:
        owner = await self._accounts.find_owner_by_api_key_digest(
            self._api_keys.digest(api_key)
        )
        if owner is None or not await self._accounts.owner_is_active(owner):
            return None
        return owner

    async def _burn_verification(self, password: str) -> None:
        """Gasta lo mismo que una verificación real: sin esto, un usuario inexistente
        responde mucho más rápido que una contraseña incorrecta y permite enumerar cuentas."""
        if self._dummy_hash is None:
            self._dummy_hash = await self._passwords.hash_password("qhub-sin-cuenta")
        await self._passwords.verify_password(password, self._dummy_hash)

    async def authenticate_credentials(
        self, identifier: str, password: str
    ) -> OwnerId | None:
        record = await self._accounts.find_login(identifier.strip().lower())
        if record is None or not record.account_active:
            await self._burn_verification(password)
            return None
        if not await self._passwords.verify_password(password, record.password_hash):
            return None
        if not await self._accounts.owner_is_active(record.owner):
            return None
        return record.owner

    async def login(self, command: LoginCommand) -> AccessToken:
        if command.identificador is not None and command.password is not None:
            owner = await self.authenticate_credentials(
                command.identificador, command.password
            )
            if owner is None:
                raise Unauthorized("Credenciales inválidas", "invalid")
        elif command.api_key:
            owner = await self.authenticate_api_key(command.api_key)
            if owner is None:
                raise Unauthorized("API key inválida", "invalid")
        else:
            raise Unauthorized(
                "Enviá {identificador, password} en el body o X-Api-Key en el header",
                "missing",
            )
        return self._tokens.issue(owner)

    async def request_password_reset(
        self, command: RequestPasswordReset
    ) -> EmailJob | None:
        """Anti-enumeración: misma respuesta genérica exista o no el email. El envío de
        correo se devuelve como "trabajo diferido" y NO se ejecuta aquí; el router lo
        encola en un BackgroundTask fuera del camino de la respuesta."""
        email_norm = command.email.strip().lower()
        target = await self._accounts.find_reset_target(email_norm)
        if target is None:
            # Gasta un verify bcrypt para equiparar el costo con la rama "existe". El valor
            # es irrelevante para el resultado y el costo; se pasa un literal neutro para no
            # sugerir que el email viaja a la verificación.
            await self._burn_verification("reset")
            return None
        raw_token = secrets.token_urlsafe(32)
        token_hash = self._api_keys.digest(raw_token)
        expira_en = self._clock.now_utc() + timedelta(minutes=self._reset_ttl_minutos)
        await self._accounts.create_password_reset(target, token_hash, expira_en)
        link = f"{self._reset_url.rstrip('/')}/qhub/restablecer?token={raw_token}"
        return EmailJob(
            to=target.email,
            subject=PASSWORD_RESET_SUBJECT,
            html=password_reset_html(link, self._reset_ttl_minutos),
        )

    async def send_reset_email(self, job: EmailJob) -> None:
        """Ejecutado por el BackgroundTask del router, fuera del camino de la respuesta.
        Consume cualquier ApplicationError (p. ej. PermanentDeliveryError): nunca llega al
        cliente, que ya recibió la respuesta genérica."""
        try:
            await self._emails.send(to=job.to, subject=job.subject, html=job.html)
        except ApplicationError:
            pass

    async def reset_password(self, command: ResetPassword) -> None:
        token_hash = self._api_keys.digest(command.token)
        now = self._clock.now_utc()
        record = await self._accounts.find_valid_reset(token_hash, now)
        if record is None:
            raise Unauthorized("El enlace no es válido o ya expiró", "invalid")
        new_hash = await self._passwords.hash_password(command.new_password)
        await self._accounts.update_password_hash(
            record.owner, record.account_id, new_hash
        )
        await self._accounts.mark_reset_used(record.id, now)
        await self._accounts.invalidate_resets_for_account(
            record.owner, record.account_id, now
        )
