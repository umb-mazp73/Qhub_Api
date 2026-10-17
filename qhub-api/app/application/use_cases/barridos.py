import logging

from app.domain.models import QueueEvent, RequestNotification, SweepResult
from app.domain.entities import Turno
from app.domain.value_objects import PersonIdentity

logger = logging.getLogger("qhub_api.application.barridos")


def minutes_until(slot_start, now) -> int:
    return max(int((slot_start - now).total_seconds() // 60), 0)


class SweepUseCases:
    def __init__(
        self,
        repository,
        events,
        notifications,
        clock,
        grace_minutes: int,
        reminder_minutes: int,
    ) -> None:
        self._repository = repository
        self._events = events
        self._notifications = notifications
        self._clock = clock
        self._grace_minutes = max(grace_minutes, 0)
        self._reminder_minutes = reminder_minutes

    async def _notify(self, command: RequestNotification) -> None:
        try:
            await self._notifications.request(command)
        except Exception:
            logger.warning("No se pudo solicitar una notificación de barrido")

    async def run_no_show(self) -> tuple[Turno, ...]:
        turns = await self._repository.expire_overdue(self._grace_minutes)
        for turn in turns:
            await self._events.publish(
                QueueEvent("turno_no_show", turn.cola_id, turn)
            )
            await self._notify(
                RequestNotification(
                    PersonIdentity(turn.owner, turn.usuario_id),
                    f"Tu turno #{turn.numero} del {turn.franja_fecha} se marcó como no "
                    "presentado: la franja terminó y no llegaste a ser atendido.",
                    turn.id,
                    "turno_no_show",
                )
            )
        return turns

    async def run_reminders(self) -> tuple[Turno, ...]:
        if self._reminder_minutes <= 0:
            return ()
        turns = await self._repository.reserve_reminders(
            self._reminder_minutes
        )
        if not turns:
            return ()
        now = self._clock.now_utc()
        for turn in turns:
            remaining = minutes_until(turn.franja_inicio, now)
            await self._notify(
                RequestNotification(
                    PersonIdentity(turn.owner, turn.usuario_id),
                    f"Recordatorio: tu turno #{turn.numero} en {turn.propietario_nombre} "
                    f"empieza en {remaining} minutos.",
                    turn.id,
                    "recordatorio",
                )
            )
        return turns

    async def run_once(self) -> SweepResult:
        no_show = await self.run_no_show()
        reminders = await self.run_reminders()
        return SweepResult(len(no_show), len(reminders))
