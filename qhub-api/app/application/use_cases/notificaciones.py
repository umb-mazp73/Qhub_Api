import logging
from uuid import UUID

from app.application.errors import NotFound
from app.domain.models import (
    NotificationJob,
    NotificationRequestResult,
    Page,
    PersistNotification,
    RequestNotification,
)
from app.domain.interfaces.clock import IdGenerator
from app.domain.interfaces.delivery import LocalLiveNotificationDelivery
from app.domain.interfaces.messaging import NotificationJobPublisher
from app.domain.interfaces.notifications import (
    NotificationPersistence,
    NotificationRepository,
)
from app.domain.entities import Notificacion
from app.domain.value_objects import PersonIdentity, TenantContext

logger = logging.getLogger("qhub_api.application.notificaciones")


class NotificationUseCases:
    def __init__(
        self,
        repository: NotificationRepository,
        persistence: NotificationPersistence,
        jobs: NotificationJobPublisher,
        delivery,
        local_live: LocalLiveNotificationDelivery | None,
        ids: IdGenerator,
    ) -> None:
        self._repository = repository
        self._persistence = persistence
        self._jobs = jobs
        self._delivery = delivery
        self._local_live = local_live
        self._ids = ids

    @property
    def job_publisher(self):
        return self._jobs

    async def request(
        self, command: RequestNotification
    ) -> NotificationRequestResult:
        key = self._ids.new_uuid()
        job = NotificationJob(
            key=key,
            identity=command.identity,
            message=command.message,
            turn_id=command.turn_id,
            notice_type=command.notice_type,
        )
        try:
            queued = await self._jobs.publish(job)
        except Exception:
            logger.warning("No se pudo publicar el trabajo de notificación")
            queued = False
        if queued:
            return NotificationRequestResult(queued=True, persisted=False)

        try:
            notification = await self._persistence.persist(
                PersistNotification(
                    identity=command.identity,
                    message=command.message,
                    turn_id=command.turn_id,
                    idempotency_key=key,
                )
            )
        except Exception:
            logger.warning("No se pudo persistir el fallback de notificación")
            return NotificationRequestResult(queued=False, persisted=False)

        if self._local_live is not None:
            try:
                await self._local_live.deliver_local(
                    notification, command.notice_type
                )
            except Exception:
                logger.warning("No se pudo entregar el fallback local")
        return NotificationRequestResult(queued=False, persisted=True)

    async def deliver_job(self, job: NotificationJob) -> Notificacion:
        notification = await self._persistence.persist(
            PersistNotification(
                identity=job.identity,
                message=job.message,
                turn_id=job.turn_id,
                idempotency_key=job.key,
            )
        )
        await self._delivery.deliver(notification, job.notice_type)
        return notification

    async def list(
        self, context: TenantContext, page: Page = Page()
    ) -> tuple[Notificacion, ...]:
        return await self._repository.list(context.identity, page)

    async def count_unread(self, identity: PersonIdentity) -> int:
        return await self._repository.count_unread(identity)

    async def mark_read(
        self, context: TenantContext, notification_id: UUID
    ) -> Notificacion:
        notification = await self._repository.get(
            context.identity, notification_id
        )
        if notification is None:
            raise NotFound("Notificación no encontrada", "notificacion")
        return await self._repository.mark_read(
            context.identity, notification_id
        )

    async def delete(
        self, context: TenantContext, notification_id: UUID
    ) -> None:
        notification = await self._repository.get(
            context.identity, notification_id
        )
        if notification is None:
            raise NotFound("Notificación no encontrada", "notificacion")
        await self._repository.delete(context.identity, notification_id)
