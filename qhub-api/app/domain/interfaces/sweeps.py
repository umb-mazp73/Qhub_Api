from typing import Protocol

from app.domain.entities import Turno


class SweepRepository(Protocol):
    async def expire_overdue(self, grace_minutes: int) -> tuple[Turno, ...]: ...
    async def reserve_reminders(self, advance_minutes: int) -> tuple[Turno, ...]: ...
