from app.domain.models import RegistrationDraft, RegistrationResult
from app.domain.interfaces.accounts import AccountRepository
from app.domain.enums import LIMITE_COLAS_POR_TIPO, PropietarioTipo
from app.domain.value_objects import LoginRecord, OwnerId
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


def _datetime(value):
    from datetime import datetime

    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
