from uuid import UUID

from app.application.errors import NotFound
from app.domain.models import (
    CreateEmpresa,
    EmpresaChanges,
    EmpresaWithApiKey,
    Page,
    UnsetType,
)
from app.domain.interfaces.clock import Clock
from app.domain.interfaces.empresas import EmpresaRepository
from app.domain.interfaces.security import ApiKeyCodec
from app.domain.entities import Empresa
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import OwnerId


class EmpresaUseCases:
    def __init__(
        self, repository: EmpresaRepository, api_keys: ApiKeyCodec, clock: Clock
    ) -> None:
        self._repository = repository
        self._api_keys = api_keys
        self._clock = clock

    async def create(self, command: CreateEmpresa) -> EmpresaWithApiKey:
        empresa = await self._repository.create(command.nombre)
        api_key = self._api_keys.generate()
        owner = OwnerId(PropietarioTipo.EMPRESA, empresa.id)
        await self._repository.insert_key_digest(owner, self._api_keys.digest(api_key))
        return EmpresaWithApiKey(empresa, api_key)

    async def list_all(self, page: Page) -> tuple[Empresa, ...]:
        return await self._repository.list_all(page)

    async def get(self, empresa_id: UUID) -> Empresa:
        empresa = await self._repository.get(empresa_id)
        if empresa is None:
            raise NotFound("Empresa no encontrada", "empresa")
        return empresa

    async def update(
        self, empresa_id: UUID, changes: EmpresaChanges
    ) -> Empresa:
        await self.get(empresa_id)
        if isinstance(changes.nombre, UnsetType) and isinstance(changes.activa, UnsetType):
            return await self.get(empresa_id)
        return await self._repository.update(empresa_id, changes)

    async def rotate_api_key(self, empresa_id: UUID) -> EmpresaWithApiKey:
        empresa = await self.get(empresa_id)
        owner = OwnerId(PropietarioTipo.EMPRESA, empresa_id)
        await self._repository.revoke_active_keys(owner, self._clock.now_utc())
        api_key = self._api_keys.generate()
        await self._repository.insert_key_digest(owner, self._api_keys.digest(api_key))
        return EmpresaWithApiKey(empresa, api_key)
