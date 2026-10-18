import logging
from uuid import UUID

from app.application.errors import Forbidden, NotFound, BadRequest
from app.domain.models import CreateTurn, Page, QueueEvent, RequestNotification, TurnQuery
from app.domain.interfaces.clock import Clock
from app.domain.interfaces.messaging import TurnEventPublisher
from app.domain.interfaces.delivery import NotificationRequester
from app.domain.interfaces.queues import QueueReader
from app.domain.interfaces.turns import TurnRepository
from app.domain.entities import Turno
from app.domain.enums import TurnoEstado
from app.domain.errors import InvalidTurnTransition
from app.domain.turn_rules import validar_transicion
from app.domain.value_objects import PersonIdentity, TenantContext

logger = logging.getLogger("qhub_api.application.turnos")


# Roles que operan la fila y pueden ver cualquier turno de su cuenta; el resto (p. ej. "cliente") solo los propios.
STAFF_ROLES = ("admin", "agente")


def _require_agent(context: TenantContext) -> None:
    if context.rol != "agente":
        raise Forbidden("Requiere uno de estos roles: agente", "agente")


def _validate(turn: Turno, action: str) -> None:
    try:
        validar_transicion(turn.estado, action)
    except InvalidTurnTransition as exc:
        raise BadRequest(exc.detail) from exc


class TurnUseCases:
    def __init__(
        self,
        repository: TurnRepository,
        queues: QueueReader,
        events: TurnEventPublisher,
        notifications: NotificationRequester,
        clock: Clock,
        enforce_ownership: bool = False,
    ) -> None:
        self._repository = repository
        self._queues = queues
        self._events = events
        self._notifications = notifications
        self._clock = clock
        self._enforce_ownership = enforce_ownership

    async def _get(self, context: TenantContext, turn_id: UUID) -> Turno:
        turn = await self._repository.get(context.identity.owner, turn_id)
        if turn is None:
            raise NotFound("Turno no encontrado", "turno")
        return turn

    def _is_foreign(self, context: TenantContext, turn: Turno) -> bool:
        return (
            self._enforce_ownership
            and context.rol not in STAFF_ROLES
            and turn.usuario_id != context.identity.usuario_id
        )

    async def _get_visible(self, context: TenantContext, turn_id: UUID) -> Turno:
        """Como `_get`, pero con ownership activo el turno de otra persona es 404 (nunca 403, igual que un recurso ajeno)."""
        turn = await self._get(context, turn_id)
        if self._is_foreign(context, turn):
            raise NotFound("Turno no encontrado", "turno")
        return turn

    async def _notify(self, command: RequestNotification) -> None:
        try:
            await self._notifications.request(command)
        except Exception:
            logger.warning("No se pudo solicitar la notificación", exc_info=True)

    async def create(self, context: TenantContext, command: CreateTurn) -> Turno:
        queue = await self._queues.get_for_owner(context.identity.owner, command.cola_id)
        if queue is None:
            raise NotFound("Cola no encontrada", "cola")
        turn = await self._repository.create_atomic(context, command)
        await self._events.publish(QueueEvent("turno_creado", queue.id, turn))
        return turn

    async def list(
        self, context: TenantContext, query: TurnQuery
    ) -> tuple[Turno, ...]:
        turns = await self._repository.list(context.identity.owner, query)
        if self._enforce_ownership and context.rol not in STAFF_ROLES:
            return tuple(t for t in turns if t.usuario_id == context.identity.usuario_id)
        return turns

    async def list_mine(
        self, context: TenantContext, page: Page = Page()
    ) -> tuple[Turno, ...]:
        return await self._repository.list_for_person(context.identity, page)

    async def get(self, context: TenantContext, turn_id: UUID) -> Turno:
        return await self._get_visible(context, turn_id)

    async def postpone(self, context: TenantContext, turn_id: UUID) -> Turno:
        turn = await self._get_visible(context, turn_id)
        _validate(turn, "posponer")
        last = await self._repository.last_waiting_position(
            context.identity.owner, turn
        )
        await self._repository.set_position(
            context.identity.owner, turn_id, last + 1
        )
        await self._repository.compact_waiting_positions(
            context.identity.owner, turn.cola_id, turn.franja_inicio
        )
        updated = await self._get(context, turn_id)
        await self._events.publish(QueueEvent("turno_pospuesto", turn.cola_id, updated))
        await self._notify(
            RequestNotification(
                PersonIdentity(updated.owner, updated.usuario_id),
                f"Tu turno #{updated.numero} pasó al final de su franja",
                updated.id,
                "turno_pospuesto",
            )
        )
        return updated

    async def cancel(self, context: TenantContext, turn_id: UUID) -> Turno:
        turn = await self._get_visible(context, turn_id)
        _validate(turn, "cancelar")
        updated = await self._repository.set_state(
            context.identity.owner, turn_id, TurnoEstado.CANCELADO
        )
        await self._repository.compact_waiting_positions(
            context.identity.owner, turn.cola_id, turn.franja_inicio
        )
        await self._events.publish(QueueEvent("turno_cancelado", turn.cola_id, updated))
        return updated

    async def attend(self, context: TenantContext, turn_id: UUID) -> Turno:
        _require_agent(context)
        turn = await self._get(context, turn_id)
        _validate(turn, "atender")
        updated = await self._repository.set_state(
            context.identity.owner,
            turn_id,
            TurnoEstado.ATENDIENDO,
            attended_at=self._clock.now_utc(),
            agent_id=context.identity.usuario_id,
        )
        await self._repository.compact_waiting_positions(
            context.identity.owner, turn.cola_id, turn.franja_inicio
        )
        await self._events.publish(QueueEvent("turno_llamado", turn.cola_id, updated))
        await self._notify(
            RequestNotification(
                PersonIdentity(updated.owner, updated.usuario_id),
                f"Tu turno #{updated.numero} está siendo atendido",
                updated.id,
                "turno_llamado",
            )
        )
        return updated

    async def finish(self, context: TenantContext, turn_id: UUID) -> Turno:
        _require_agent(context)
        turn = await self._get(context, turn_id)
        _validate(turn, "finalizar")
        updated = await self._repository.set_state(
            context.identity.owner,
            turn_id,
            TurnoEstado.FINALIZADO,
            finished_at=self._clock.now_utc(),
        )
        await self._events.publish(QueueEvent("cola_actualizada", turn.cola_id, updated))
        return updated

    async def mark_no_show(self, context: TenantContext, turn_id: UUID) -> Turno:
        _require_agent(context)
        turn = await self._get(context, turn_id)
        _validate(turn, "no_show")
        updated = await self._repository.set_state(
            context.identity.owner,
            turn_id,
            TurnoEstado.NO_SHOW,
            finished_at=self._clock.now_utc(),
        )
        await self._repository.compact_waiting_positions(
            context.identity.owner, turn.cola_id, turn.franja_inicio
        )
        await self._events.publish(QueueEvent("cola_actualizada", turn.cola_id, updated))
        return updated
