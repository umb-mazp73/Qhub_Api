import asyncio
import logging

import httpx

from app.domain.entities import Notificacion

logger = logging.getLogger("qhub_api.delivery.webhook")


class WebhookNotificationChannel:
    """Avisa de inmediato a un servicio externo (la función `qhub-aviso` de Supabase) cuando
    se crea un aviso de turno, para que mande el push y el correo en el momento en vez de
    esperar a una revisión periódica.

    Es best-effort y no bloquea: el POST sale en una tarea aparte con timeout corto y
    cualquier fallo solo deja un warning, así los demás canales (websocket/log/email) no se
    retrasan ni se rompen. No registra el mensaje del aviso ni datos de la persona."""

    name = "webhook"

    def __init__(self, url: str, secret: str, timeout: float = 5.0, client_factory=None) -> None:
        self._url = url
        self._secret = secret
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._tasks: set[asyncio.Task] = set()

    @staticmethod
    def payload(notification: Notificacion, notice_type: str) -> dict:
        return {
            "propietario_tipo": notification.identity.owner.tipo.value,
            "propietario_id": str(notification.identity.owner.id),
            "usuario_id": notification.identity.usuario_id,
            "notificacion": {
                "id": str(notification.id),
                "turno_id": str(notification.turno_id) if notification.turno_id else None,
                "mensaje": notification.mensaje,
                "leida": notification.leida,
                "creada_en": notification.creada_en.isoformat(),
                "tipo_aviso": notice_type,
            },
        }

    async def _post(self, body: dict) -> None:
        try:
            async with self._client_factory() as client:
                resp = await client.post(
                    self._url, json=body, headers={"x-aviso-secret": self._secret}
                )
            if resp.status_code >= 400:
                logger.warning("Webhook de avisos rechazado (HTTP %s)", resp.status_code)
        except Exception:
            logger.warning("No se pudo avisar al webhook de avisos")

    async def deliver(self, notification: Notificacion, notice_type: str) -> None:
        task = asyncio.create_task(self._post(self.payload(notification, notice_type)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
