from typing import Protocol
from uuid import UUID

from app.domain.models import Page, PersistNotification
from app.domain.entities import Notificacion
from app.domain.value_objects import PersonIdentity


class NotificationPersistence(Protocol):
    async def persist(self, command: PersistNotification) -> Notificacion: ...


class NotificationRepository(Protocol):
    async def list(
        self, identity: PersonIdentity, page: Page
    ) -> tuple[Notificacion, ...]: ...
    async def count_unread(self, identity: PersonIdentity) -> int: ...
    async def get(
        self, identity: PersonIdentity, notification_id: UUID
    ) -> Notificacion | None: ...
    async def mark_read(
        self, identity: PersonIdentity, notification_id: UUID
    ) -> Notificacion: ...
    async def delete(self, identity: PersonIdentity, notification_id: UUID) -> None: ...
