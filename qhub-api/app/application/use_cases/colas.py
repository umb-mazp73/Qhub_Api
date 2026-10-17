import logging
from datetime import date
from uuid import UUID

from app.application.errors import Forbidden, NotFound, UnprocessableInput
from app.domain.models import (
    CreateQueue,
    QueueChanges,
    QueueSchedule,
    ScheduleResult,
    UnsetType,
)
from app.domain.interfaces.clock import Clock
from app.domain.interfaces.messaging import QueueTopologyProvisioner
from app.domain.interfaces.queues import QueueReader, QueueWriter
from app.domain.entities import Cola
from app.domain.enums import LIMITE_COLAS_POR_TIPO
from app.domain.errors import InvalidSchedule
from app.domain.queue_rules import cupos_por_franja, franjas_por_dia, validar_horario
from app.domain.value_objects import Franja, QueueLimit, QueueState, QueueSubscription, TenantContext

logger = logging.getLogger("qhub_api.application.colas")


def _require_role(context: TenantContext, role: str) -> None:
    if context.rol != role:
        raise Forbidden(f"Requiere uno de estos roles: {role}", role)


def _schedule_result(cola: Cola) -> ScheduleResult:
    slots = franjas_por_dia(
        cola.hora_apertura, cola.hora_cierre, cola.duracion_franja_minutos
    )
    capacity = cupos_por_franja(
        cola.duracion_franja_minutos,
        cola.duracion_turno_minutos,
        cola.puestos,
    )
    total = slots * capacity
    daily = cola.capacidad_diaria
    return ScheduleResult(
        cola=cola,
        franjas_por_dia=slots,
        cupos_por_franja=capacity,
        turnos_por_dia=min(total, daily) if daily > 0 else total,
    )


class QueueUseCases:
    def __init__(
        self,
        reader: QueueReader,
        writer: QueueWriter,
        topology: QueueTopologyProvisioner,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._topology = topology
        self._clock = clock

    async def _provision(self, cola: Cola) -> None:
        """Best-effort: la base ya quedó bien; si el broker no responde, el barrido del
        worker declara la cola en la próxima pasada."""
        try:
            await self._topology.ensure_queue(
                QueueSubscription(cola.id, cola.rabbitmq_queue_name)
            )
        except Exception:
            logger.warning(
                "No se pudo aprovisionar la cola de RabbitMQ; se reintentará en el barrido",
                exc_info=True,
            )

    async def _release(self, cola: Cola) -> None:
        """Una cola desactivada no debe ocupar para siempre una de las colas del broker
        (el plan free topea en 150, compartidas por todas las cuentas)."""
        try:
            await self._topology.release_queue(
                QueueSubscription(cola.id, cola.rabbitmq_queue_name)
            )
        except Exception:
            logger.warning("No se pudo liberar la cola de RabbitMQ", exc_info=True)

    async def create(self, context: TenantContext, command: CreateQueue) -> Cola:
        _require_role(context, "admin")
        cola = await self._writer.create(context.identity.owner, command)
        await self._provision(cola)
        return cola

    async def list(
        self, context: TenantContext, active: bool | None = None
    ) -> tuple[Cola, ...]:
        colas = await self._reader.list_for_owner(context.identity.owner)
        if active is None:
            return colas
        return tuple(cola for cola in colas if cola.activa is active)

    async def limit(self, context: TenantContext) -> QueueLimit:
        owner = context.identity.owner
        active = await self._reader.count_active(owner)
        limit = LIMITE_COLAS_POR_TIPO[owner.tipo]
        return QueueLimit(owner.tipo, limit, active, max(limit - active, 0))

    async def get(self, context: TenantContext, queue_id: UUID) -> Cola:
        cola = await self._reader.get_for_owner(context.identity.owner, queue_id)
        if cola is None:
            raise NotFound("Cola no encontrada", "cola")
        return cola

    async def update(
        self, context: TenantContext, queue_id: UUID, changes: QueueChanges
    ) -> Cola:
        _require_role(context, "admin")
        before = await self.get(context, queue_id)
        if all(isinstance(value, UnsetType) for value in (changes.nombre, changes.descripcion, changes.activa)):
            return before
        updated = await self._writer.update(context.identity.owner, queue_id, changes)
        # Solo una cola ACTIVA es dueña de una cola del broker. Las archivadas no tienen
        # ninguna, y su nombre puede ya ser el de otra cola activa: no se les toca la del broker.
        # Renombrar una cola cambia su nombre en el broker (lo recalcula un trigger).
        renamed = updated.rabbitmq_queue_name != before.rabbitmq_queue_name
        if before.activa and (renamed or not updated.activa):
            await self._release(before)
        if updated.activa and (renamed or not before.activa):
            await self._provision(updated)
        return updated

    async def deactivate(self, context: TenantContext, queue_id: UUID) -> None:
        _require_role(context, "admin")
        cola = await self.get(context, queue_id)
        await self._writer.deactivate(context.identity.owner, queue_id)
        if cola.activa:  # eliminar una ya archivada no debe tocar la cola de otra con su nombre
            await self._release(cola)

    async def get_schedule(
        self, context: TenantContext, queue_id: UUID
    ) -> ScheduleResult:
        return _schedule_result(await self.get(context, queue_id))

    async def replace_schedule(
        self,
        context: TenantContext,
        queue_id: UUID,
        schedule: QueueSchedule,
    ) -> ScheduleResult:
        _require_role(context, "admin")
        await self.get(context, queue_id)
        try:
            validar_horario(
                schedule.hora_apertura,
                schedule.hora_cierre,
                schedule.duracion_franja_minutos,
                schedule.duracion_turno_minutos,
            )
        except InvalidSchedule as exc:
            raise UnprocessableInput(exc.detail) from exc
        cola = await self._writer.replace_schedule(
            context.identity.owner, queue_id, schedule
        )
        return _schedule_result(cola)

    async def list_slots(
        self, context: TenantContext, queue_id: UUID, day: date | None
    ) -> tuple[Franja, ...]:
        await self.get(context, queue_id)
        return await self._reader.list_slots(
            context.identity.owner, queue_id, day, self._clock.now_utc()
        )

    async def state(
        self, context: TenantContext, queue_id: UUID
    ) -> QueueState:
        await self.get(context, queue_id)
        return await self._reader.state(context.identity.owner, queue_id)
