import logging

from app.domain.entities import Notificacion

logger = logging.getLogger("qhub_api.delivery.log")


class LogNotificationChannel:
    """Canal de entrega que solo deja constancia en el log (no registra el texto del aviso).

    Es también el molde para enganchar un canal real (push, email, SMS): una clase con
    `name` y `async deliver(notification, notice_type)` que se agrega en
    `Dependencies._select_channels` y se activa con `NOTIFICACIONES_CANALES`."""

    name = "log"

    async def deliver(self, notification: Notificacion, notice_type: str) -> None:
        logger.info(
            "Notificación entregada (canal: log) usuario=%s tipo=%s",
            notification.identity.usuario_id,
            notice_type,
        )
