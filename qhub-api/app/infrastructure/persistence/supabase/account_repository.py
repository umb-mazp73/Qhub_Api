from datetime import datetime
from uuid import UUID

from app.application.errors import PersistenceFailure
from app.domain.models import RegistrationDraft, RegistrationResult
from app.domain.interfaces.accounts import AccountRepository
from app.domain.enums import LIMITE_COLAS_POR_TIPO, PropietarioTipo
from app.domain.value_objects import (
    LoginRecord,
    OwnerId,
    PasswordResetRecord,
    ResetTarget,
)
from app.infrastructure.persistence.supabase.error_mapping import map_registration_error


class SupabaseAccountRepository(AccountRepository):
    def __init__(self, client) -> None:
        self._client = client

    async def identifier_exists(self, username_norm: str, email_norm: str) -> bool:
        for table in ("control_empresas", "usuarios"):
            result = (
                await self._client.table(table)
                .select("id")
                .or_(f"email.ilike.{email_norm},nombre_usuario.ilike.{username_norm}")
                .limit(1)
                .execute()
            )
            if result.data:
                return True
        return False

    async def find_login(self, identifier_norm: str) -> LoginRecord | None:
        for owner_type, table, owner_column in (
            (PropietarioTipo.EMPRESA, "control_empresas", "empresa_id"),
            (PropietarioTipo.USUARIO, "usuarios", "id"),
        ):
            result = (
                await self._client.table(table)
                .select(f"{owner_column}, password_hash, activa")
                .or_(
                    f"email.ilike.{identifier_norm},nombre_usuario.ilike.{identifier_norm}"
                )
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                return LoginRecord(
                    OwnerId(owner_type, __import__("uuid").UUID(str(row[owner_column]))),
                    str(row["password_hash"]),
                    bool(row.get("activa", True)),
                    True,
                )
        return None

    async def find_owner_by_api_key_digest(self, digest: str) -> OwnerId | None:
        result = (
            await self._client.table("api_keys")
            .select("propietario_tipo, propietario_id")
            .eq("api_key_hash", digest)
            .eq("activa", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        return OwnerId(
            PropietarioTipo(row["propietario_tipo"]),
            __import__("uuid").UUID(str(row["propietario_id"])),
        )

    async def owner_is_active(self, owner: OwnerId) -> bool:
        table = "empresas" if owner.tipo is PropietarioTipo.EMPRESA else "usuarios"
        result = (
            await self._client.table(table)
            .select("id, activa")
            .eq("id", str(owner.id))
            .limit(1)
            .execute()
        )
        return bool(result.data) and bool(result.data[0].get("activa", False))

    async def register(self, draft: RegistrationDraft) -> RegistrationResult:
        try:
            if draft.tipo_cuenta is PropietarioTipo.USUARIO:
                result = await self._client.rpc(
                    "registrar_usuario",
                    {
                        "p_nombre": draft.nombre,
                        "p_apellido": draft.apellido,
                        "p_nombre_usuario": draft.nombre_usuario,
                        "p_email": draft.email,
                        "p_password_hash": draft.password_hash,
                        "p_pais": draft.pais,
                        "p_ciudad": draft.ciudad,
                    },
                ).execute()
                row = result.data
                owner = OwnerId(PropietarioTipo.USUARIO, __import__("uuid").UUID(str(row["id"])))
            elif draft.owner is not None:
                result = (
                    await self._client.table("control_empresas")
                    .insert(
                        {
                            "empresa_id": str(draft.owner.id),
                            "nombre": draft.nombre,
                            "apellido": draft.apellido,
                            "nombre_usuario": draft.nombre_usuario,
                            "email": draft.email,
                            "password_hash": draft.password_hash,
                            "pais": draft.pais,
                            "ciudad": draft.ciudad,
                            "acepto_terminos": True,
                            "acepto_terminos_en": draft.acepto_terminos_en.isoformat(),
                        }
                    )
                    .execute()
                )
                row = result.data[0]
                owner = draft.owner
            else:
                result = await self._client.rpc(
                    "registrar_empresa",
                    {
                        "p_nombre_empresa": draft.nombre_empresa,
                        "p_nombre": draft.nombre,
                        "p_apellido": draft.apellido,
                        "p_nombre_usuario": draft.nombre_usuario,
                        "p_email": draft.email,
                        "p_password_hash": draft.password_hash,
                        "p_pais": draft.pais,
                        "p_ciudad": draft.ciudad,
                    },
                ).execute()
                row = result.data
                owner = OwnerId(PropietarioTipo.EMPRESA, __import__("uuid").UUID(str(row["empresa_id"])))
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise map_registration_error(exc) from exc
            raise

        return RegistrationResult(
            owner=owner,
            nombre_usuario=str(row["nombre_usuario"]),
            email=str(row["email"]),
            nombre_empresa=row.get("nombre_empresa"),
            limite_colas=LIMITE_COLAS_POR_TIPO[owner.tipo],
            creada_en=_datetime(row["creada_en"]),
        )

    async def find_reset_target(self, email_norm: str) -> ResetTarget | None:
        for owner_type, table, owner_column in (
            (PropietarioTipo.EMPRESA, "control_empresas", "empresa_id"),
            (PropietarioTipo.USUARIO, "usuarios", "id"),
        ):
            # Fix #1: evitar duplicar "id, id, email" cuando owner_column == "id" (usuarios).
            cols = "id, email" if owner_column == "id" else f"id, {owner_column}, email"
            try:
                result = (
                    await self._client.table(table)
                    .select(cols)
                    # Fix #2: igualdad exacta sobre el email normalizado (ya se escribe en
                    # minúsculas al registrar). Nunca .ilike: % y _ son comodines y
                    # filtrarían el email equivocado (envío a otra cuenta + fuga de
                    # enumeración).
                    .eq("email", email_norm)
                    .limit(1)
                    .execute()
                )
            except Exception as exc:
                raise PersistenceFailure(operation="find_reset_target") from exc
            if result.data:
                row = result.data[0]
                return ResetTarget(
                    owner=OwnerId(owner_type, UUID(str(row[owner_column]))),
                    account_id=UUID(str(row["id"])),
                    email=str(row["email"]),
                )
        return None

    async def create_password_reset(
        self, target: ResetTarget, token_hash: str, expira_en: datetime
    ) -> None:
        try:
            await (
                self._client.table("password_resets")
                .insert(
                    {
                        "propietario_tipo": target.owner.tipo.value,
                        "propietario_id": str(target.owner.id),
                        "account_id": str(target.account_id),
                        "token_hash": token_hash,
                        "email": target.email,
                        "expira_en": expira_en.isoformat(),
                    }
                )
                .execute()
            )
        except Exception as exc:
            raise PersistenceFailure(operation="create_password_reset") from exc

    async def find_valid_reset(
        self, token_hash: str, now: datetime
    ) -> PasswordResetRecord | None:
        try:
            result = (
                await self._client.table("password_resets")
                .select("*")
                .eq("token_hash", token_hash)
                .is_("usado_en", "null")
                .gte("expira_en", now.isoformat())
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise PersistenceFailure(operation="find_valid_reset") from exc
        if not result.data:
            return None
        row = result.data[0]
        return PasswordResetRecord(
            id=UUID(str(row["id"])),
            owner=OwnerId(
                PropietarioTipo(row["propietario_tipo"]),
                UUID(str(row["propietario_id"])),
            ),
            account_id=UUID(str(row["account_id"])),
            email=str(row["email"]),
            expira_en=_datetime(row["expira_en"]),
            usado_en=_datetime(row["usado_en"]) if row.get("usado_en") else None,
        )

    async def mark_reset_used(self, reset_id: UUID, used_at: datetime) -> None:
        try:
            await (
                self._client.table("password_resets")
                .update({"usado_en": used_at.isoformat()})
                .eq("id", str(reset_id))
                .execute()
            )
        except Exception as exc:
            raise PersistenceFailure(operation="mark_reset_used") from exc

    async def update_password_hash(
        self, owner: OwnerId, account_id: UUID, password_hash: str
    ) -> None:
        table = (
            "control_empresas"
            if owner.tipo is PropietarioTipo.EMPRESA
            else "usuarios"
        )
        try:
            # Fix #5: siempre por la PK real (id), nunca .ilike("email", ...).
            result = (
                await self._client.table(table)
                .update({"password_hash": password_hash})
                .eq("id", str(account_id))
                .execute()
            )
        except Exception as exc:
            raise PersistenceFailure(operation="update_password_hash") from exc
        # Defensa en profundidad: exactamente una fila afectada. 0 = fila borrada en
        # carrera; >1 = dato corrupto (no debería ocurrir con filtro por PK).
        if len(result.data) != 1:
            raise PersistenceFailure(operation="update_password_hash")

    async def invalidate_resets_for_account(
        self, owner: OwnerId, account_id: UUID, now: datetime
    ) -> None:
        try:
            await (
                self._client.table("password_resets")
                .update({"usado_en": now.isoformat()})
                .eq("propietario_tipo", owner.tipo.value)
                .eq("account_id", str(account_id))
                .is_("usado_en", "null")
                .execute()
            )
        except Exception as exc:
            raise PersistenceFailure(operation="invalidate_resets_for_account") from exc


def _datetime(value):
    from datetime import datetime

    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
