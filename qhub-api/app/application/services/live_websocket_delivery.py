import logging

from app.domain.models import FanoutNotification, PersonalNotificationWire
from app.domain.interfaces.delivery import PersonalNotificationSink
from app.domain.interfaces.messaging import NotificationFanoutPublisher
from app.domain.entities import Notificacion

logger = logging.getLogger("qhub_api.delivery.websocket")


class LiveWebSocketDeliveryChannel:
    name = "websocket"

    def __init__(
        self,
        fanout: NotificationFanoutPublisher,
        local_sink: PersonalNotificationSink,
    ) -> None:
        self._fanout = fanout
        self._local_sink = local_sink

    async def deliver(
        self, notification: Notificacion, notice_type: str
    ) -> None:
        message = PersonalNotificationWire.from_notification(
            notification, notice_type
        )
        try:
            if await self._fanout.publish(
                FanoutNotification(notification.identity, message)
            ):
                return
        except Exception:
            logger.warning("No se pudo difundir la notificación")
        await self._send_local(notification, message)

    async def deliver_local(
        self, notification: Notificacion, notice_type: str
    ) -> int:
        message = PersonalNotificationWire.from_notification(
            notification, notice_type
        )
        return await self._send_local(notification, message)

    async def _send_local(
        self,
        notification: Notificacion,
        message: PersonalNotificationWire,
    ) -> int:
        try:
            return await self._local_sink.send(
                notification.identity, message
            )
        except Exception:
            logger.warning("No se pudo entregar la notificación local")
            return 0
