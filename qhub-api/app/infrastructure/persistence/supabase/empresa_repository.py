from app.domain.models import EmpresaChanges, Page, UnsetType
from app.domain.interfaces.empresas import EmpresaRepository
from app.domain.entities import Empresa
from app.domain.value_objects import OwnerId
from app.infrastructure.persistence.supabase.mappers import empresa_from_row


class SupabaseEmpresaRepository(EmpresaRepository):
    def __init__(self, client) -> None:
        self._client = client

    async def create(self, name: str) -> Empresa:
        result = await self._client.table("empresas").insert({"nombre": name}).execute()
        return empresa_from_row(result.data[0])

    async def list_all(self, page: Page) -> tuple[Empresa, ...]:
        result = await (
            self._client.table("empresas")
            .select("*")
            .order("creada_en")
            .order("id")
            .range(page.offset, page.offset + page.limit - 1)
            .execute()
        )
        return tuple(empresa_from_row(row) for row in result.data)

    async def get(self, empresa_id) -> Empresa | None:
        result = (
            await self._client.table("empresas")
            .select("*")
            .eq("id", str(empresa_id))
            .limit(1)
            .execute()
        )
        return empresa_from_row(result.data[0]) if result.data else None

    async def update(self, empresa_id, changes: EmpresaChanges) -> Empresa:
        values = {
            name: value
            for name, value in (("nombre", changes.nombre), ("activa", changes.activa))
            if not isinstance(value, UnsetType)
        }
        result = (
            await self._client.table("empresas")
            .update(values)
            .eq("id", str(empresa_id))
            .execute()
        )
        return empresa_from_row(result.data[0])

    async def revoke_active_keys(self, owner: OwnerId, at) -> None:
        await self._client.table("api_keys").update(
            {"activa": False, "revocada_en": at.isoformat()}
        ).eq("propietario_tipo", owner.tipo.value).eq(
            "propietario_id", str(owner.id)
        ).eq("activa", True).execute()

    async def insert_key_digest(self, owner: OwnerId, digest: str) -> None:
        await self._client.table("api_keys").insert(
            {
                "propietario_tipo": owner.tipo.value,
                "propietario_id": str(owner.id),
                "api_key_hash": digest,
                "activa": True,
            }
        ).execute()
