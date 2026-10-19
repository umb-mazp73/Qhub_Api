import logging

import httpx

from app.application.errors import PermanentDeliveryError

logger = logging.getLogger("qhub_api.delivery.email")


class BrevoEmailSender:
    """POST a la API HTTP de Brevo. Reutiliza httpx (ya es dependencia del proyecto).

    Brevo permite enviar a cualquier destinatario sin verificar un dominio: basta con
    verificar el remitente (EMAIL_FROM) como "sender" en el panel de Brevo.
    """

    _URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key: str, email_from: str) -> None:
        self._api_key = api_key
        self._from = email_from

    async def send(self, *, to: str, subject: str, html: str) -> None:
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "sender": {"email": self._from},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # Transitorio: el caso de uso ya respondió genérico; solo se registra (sin
            # cuerpo ni api-key).
            logger.warning("No se pudo contactar a Brevo")
            raise PermanentDeliveryError(
                detail="Fallo de red al enviar el correo",
                channel="email",
                reason="rejected",
            ) from exc
        if resp.status_code >= 400:
            logger.warning("Brevo rechazó el envío (status=%s)", resp.status_code)
            raise PermanentDeliveryError(
                detail="El proveedor de correo rechazó el envío",
                channel="email",
                reason="rejected",
            )
