from typing import Protocol

from app.domain.models import PersonalNotificationWire, RequestNotification, NotificationRequestResult
from app.domain.entities import Notificacion
from app.domain.value_objects import PersonIdentity


class PersonalNotificationSink(Protocol):
    async def send(
        self, identity: PersonIdentity, message: PersonalNotificationWire
    ) -> int: ...


class NotificationDeliveryChannel(Protocol):
    name: str

    async def deliver(self, notification: Notificacion, notice_type: str) -> None: ...


class NotificationEmailResolver(Protocol):
    """Resuelve el correo del destinatario de un aviso (o `None` si no hay uno).

    Abstracción de la que depende EmailNotificationChannel; SupabaseAccountRepository la
    satisface estructuralmente."""

    async def email_for(self, identity: PersonIdentity) -> str | None: ...


class LocalLiveNotificationDelivery(Protocol):
    async def deliver_local(self, notification: Notificacion, notice_type: str) -> int: ...


class NotificationRequester(Protocol):
    async def request(self, command: RequestNotification) -> NotificationRequestResult: ...
