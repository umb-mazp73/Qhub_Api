from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.models import CreateTurn, Page, TurnQuery
from app.domain.entities import Turno
from app.domain.enums import TurnoEstado
from app.domain.value_objects import OwnerId, PersonIdentity, TenantContext


class TurnRepository(Protocol):
    async def get(self, owner: OwnerId, turn_id: UUID) -> Turno | None: ...
    async def list(self, owner: OwnerId, query: TurnQuery) -> tuple[Turno, ...]: ...
    async def list_for_person(
        self, identity: PersonIdentity, page: Page
    ) -> tuple[Turno, ...]: ...
    async def create_atomic(self, context: TenantContext, command: CreateTurn) -> Turno: ...
    async def last_waiting_position(self, owner: OwnerId, turn: Turno) -> int: ...
    async def set_position(self, owner: OwnerId, turn_id: UUID, position: int) -> None: ...
    async def set_state(
        self,
        owner: OwnerId,
        turn_id: UUID,
        state: TurnoEstado,
        attended_at: datetime | None = None,
        finished_at: datetime | None = None,
        agent_id: str | None = None,
    ) -> Turno: ...
    async def compact_waiting_positions(
        self, owner: OwnerId, queue_id: UUID, slot_start: datetime
    ) -> None: ...
