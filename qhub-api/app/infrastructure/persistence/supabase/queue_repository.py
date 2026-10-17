import asyncio
from datetime import date, datetime
from uuid import UUID

from app.domain.models import CreateQueue, QueueChanges, QueueSchedule, UnsetType
from app.domain.interfaces.queues import QueueReader, QueueWriter
from app.domain.entities import Cola
from app.domain.enums import TurnoEstado
from app.domain.value_objects import Franja, OwnerId, QueueState
from app.infrastructure.persistence.supabase.error_mapping import map_queue_error
from app.infrastructure.persistence.supabase.mappers import cola_from_row, franja_from_row


class SupabaseQueueRepository(QueueReader, QueueWriter):
    def __init__(self, client) -> None:
        self._client = client

    def _owned(self, owner: OwnerId):
        return (
            self._client.table("colas")
            .select("*")
            .eq("propietario_tipo", owner.tipo.value)
            .eq("propietario_id", str(owner.id))
        )

    async def list_for_owner(self, owner: OwnerId) -> tuple[Cola, ...]:
        result = await self._owned(owner).execute()
        return tuple(cola_from_row(row) for row in result.data)

    async def get_for_owner(self, owner: OwnerId, queue_id: UUID) -> Cola | None:
        result = await self._owned(owner).eq("id", str(queue_id)).limit(1).execute()
        return cola_from_row(result.data[0]) if result.data else None

    async def count_active(self, owner: OwnerId) -> int:
        result = await self._owned(owner).eq("activa", True).execute()
        return len(result.data)

    async def list_slots(
        self, owner: OwnerId, queue_id: UUID, day: date | None, now: datetime
    ) -> tuple[Franja, ...]:
        if day is None:
            current = await self._client.rpc(
                "franja_de_cola",
                {"p_cola_id": str(queue_id), "p_momento": now.astimezone().isoformat()},
            ).execute()
            day = (
                datetime.fromisoformat(str(current.data).replace("Z", "+00:00")).date()
                if current.data
                else now.date()
            )
        result = await self._client.rpc(
            "listar_franjas", {"p_cola_id": str(queue_id), "p_fecha": day.isoformat()}
        ).execute()
        return tuple(franja_from_row(row) for row in (result.data or ()))

    async def state(self, owner: OwnerId, queue_id: UUID) -> QueueState:
        def query(state: TurnoEstado):
            return (
                self._client.table("turnos")
                .select("id", count="exact")
                .eq("propietario_tipo", owner.tipo.value)
                .eq("propietario_id", str(owner.id))
                .eq("cola_id", str(queue_id))
                .eq("estado", state.value)
                .execute()
            )

        waiting, attending = await asyncio.gather(
            query(TurnoEstado.EN_ESPERA), query(TurnoEstado.ATENDIENDO)
        )
        return QueueState(queue_id, waiting.count or 0, attending.count or 0)

    async def create(self, owner: OwnerId, command: CreateQueue) -> Cola:
        row = {
            "nombre": command.nombre,
            "descripcion": command.descripcion,
            "propietario_tipo": owner.tipo.value,
            "propietario_id": str(owner.id),
        }
        for name in (
            "duracion_franja_minutos",
            "dias_atencion",
            "duracion_turno_minutos",
            "puestos",
            "capacidad_diaria",
            "dias_anticipacion_maxima",
        ):
            value = getattr(command, name)
            if value is not None:
                row[name] = list(value) if isinstance(value, tuple) else value
        if command.hora_apertura is not None:
            row["hora_apertura"] = command.hora_apertura.isoformat()
        if command.hora_cierre is not None:
            row["hora_cierre"] = command.hora_cierre.isoformat()
        try:
            result = await self._client.table("colas").insert(row).execute()
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise map_queue_error(exc, "create_queue", owner_type=owner.tipo) from exc
            raise
        return cola_from_row(result.data[0])

    async def update(
        self, owner: OwnerId, queue_id: UUID, changes: QueueChanges
    ) -> Cola:
        values = {
            name: value
            for name, value in (
                ("nombre", changes.nombre),
                ("descripcion", changes.descripcion),
                ("activa", changes.activa),
            )
            if not isinstance(value, UnsetType)
        }
        try:
            result = (
                await self._client.table("colas")
                .update(values)
                .eq("propietario_tipo", owner.tipo.value)
                .eq("propietario_id", str(owner.id))
                .eq("id", str(queue_id))
                .execute()
            )
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise map_queue_error(exc, "update_queue", owner_type=owner.tipo) from exc
            raise
        return cola_from_row(result.data[0])

    async def deactivate(self, owner: OwnerId, queue_id: UUID) -> None:
        await self._client.table("colas").update({"activa": False}).eq(
            "propietario_tipo", owner.tipo.value
        ).eq("propietario_id", str(owner.id)).eq("id", str(queue_id)).execute()

    async def replace_schedule(
        self, owner: OwnerId, queue_id: UUID, schedule: QueueSchedule
    ) -> Cola:
        values = {
            "hora_apertura": schedule.hora_apertura.isoformat(),
            "hora_cierre": schedule.hora_cierre.isoformat(),
            "duracion_franja_minutos": schedule.duracion_franja_minutos,
            "dias_atencion": list(schedule.dias_atencion),
            "duracion_turno_minutos": schedule.duracion_turno_minutos,
            "puestos": schedule.puestos,
            "capacidad_diaria": schedule.capacidad_diaria,
            "dias_anticipacion_maxima": schedule.dias_anticipacion_maxima,
        }
        if schedule.zona_horaria is not None:
            values["zona_horaria"] = schedule.zona_horaria
        try:
            result = (
                await self._client.table("colas")
                .update(values)
                .eq("propietario_tipo", owner.tipo.value)
                .eq("propietario_id", str(owner.id))
                .eq("id", str(queue_id))
                .execute()
            )
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise map_queue_error(exc, "update_schedule", owner_type=owner.tipo) from exc
            raise
        return cola_from_row(result.data[0])
