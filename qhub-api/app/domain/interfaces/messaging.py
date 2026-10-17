from typing import Protocol
from uuid import UUID

from app.domain.models import (
    FanoutNotification,
    NotificationJob,
    QueueEvent,
    QueueEventEnvelope,
)
from app.domain.value_objects import QueueSubscription


class QueueTopologyProvisioner(Protocol):
    async def ensure_queue(self, subscription: QueueSubscription) -> None: ...
    async def release_queue(self, subscription: QueueSubscription) -> None: ...


class TurnEventPublisher(Protocol):
    async def publish(self, event: QueueEvent) -> bool:
        """True si el evento quedó en el broker, False si no se pudo (sin broker)."""
        ...


class NotificationJobPublisher(Protocol):
    async def publish(self, job: NotificationJob, attempt: int = 0) -> bool: ...


class NotificationFanoutPublisher(Protocol):
    async def publish(self, message: FanoutNotification) -> bool: ...


class QueueEventFanoutPublisher(Protocol):
    async def publish(self, event: QueueEventEnvelope) -> bool: ...


class QueueEventSink(Protocol):
    async def send(
        self, queue_id: UUID, event: QueueEventEnvelope
    ) -> int: ...
