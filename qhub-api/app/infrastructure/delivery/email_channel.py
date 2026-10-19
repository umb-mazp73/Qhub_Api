import logging

from app.domain.entities import Notificacion
from app.domain.interfaces.delivery import NotificationEmailResolver
from app.domain.interfaces.email import EmailSender
from app.infrastructure.delivery.templates.notification_email import (
    notification_email_html,
    subject_for,
)

logger = logging.getLogger("qhub_api.delivery.email")


class EmailNotificationChannel:
    """Canal de entrega por correo (vía Brevo), additive al canal en vivo.

    Envía SOLO para los tipos de aviso importantes del cliente (los que `subject_for`
    reconoce); cualquier otro tipo se omite. Es best-effort: todo el cuerpo va dentro de
    un try/except con un warning, y nunca re-lanza, así un correo sin destinatario o un
    fallo de Brevo no bloquea los demás canales (websocket/log). No registra el cuerpo del
    aviso ni la dirección, igual que el canal de log."""

    name = "email"

    def __init__(self, sender: EmailSender, resolver: NotificationEmailResolver) -> None:
        self._sender = sender
        self._resolver = resolver

    async def deliver(self, notification: Notificacion, notice_type: str) -> None:
        try:
            subject = subject_for(notice_type)
            if subject is None:
                return  # tipo no importante para correo: se omite
            to = await self._resolver.email_for(notification.identity)
            if not to:
                logger.warning(
                    "Aviso sin correo de destinatario (canal: email) usuario=%s tipo=%s",
                    notification.identity.usuario_id,
                    notice_type,
                )
                return
            await self._sender.send(
                to=to,
                subject=subject,
                html=notification_email_html(notification.mensaje),
            )
            logger.info(
                "Notificación entregada (canal: email) usuario=%s tipo=%s",
                notification.identity.usuario_id,
                notice_type,
            )
        except Exception:
            logger.warning(
                "No se pudo entregar la notificación (canal: email) usuario=%s tipo=%s",
                notification.identity.usuario_id,
                notice_type,
            )
