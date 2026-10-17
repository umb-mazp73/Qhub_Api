from app.domain.interfaces.sweeps import SweepRepository
from app.infrastructure.persistence.supabase.mappers import turno_from_row


class SupabaseSweepRepository(SweepRepository):
    def __init__(self, client) -> None:
        self._client = client

    @property
    def client(self):
        return self._client

    async def expire_overdue(self, grace_minutes: int):
        result = await self._client.rpc(
            "expirar_turnos_vencidos",
            {"p_gracia_minutos": max(grace_minutes, 0)},
        ).execute()
        return tuple(turno_from_row(row) for row in (result.data or ()))

    async def reserve_reminders(self, advance_minutes: int):
        if advance_minutes <= 0:
            return ()
        result = await self._client.rpc(
            "marcar_turnos_para_recordar",
            {"p_anticipacion_minutos": advance_minutes},
        ).execute()
        return tuple(turno_from_row(row) for row in (result.data or ()))
