import logging

import httpx

from app.application.errors import PermanentDeliveryError

logger = logging.getLogger("qhub_api.delivery.email")


class ResendEmailSender:
    """POST a la API HTTP de Resend. Reutiliza httpx (ya es dependencia del proyecto)."""

    _URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, email_from: str) -> None:
        self._api_key = api_key
        self._from = email_from

    async def send(self, *, to: str, subject: str, html: str) -> None:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {"from": self._from, "to": [to], "subject": subject, "html": html}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # Transitorio: el caso de uso ya respondió genérico; solo se registra (sin
            # cuerpo ni token).
            logger.warning("No se pudo contactar a Resend")
            raise PermanentDeliveryError(
                detail="Fallo de red al enviar el correo",
                channel="email",
                reason="rejected",
            ) from exc
        if resp.status_code >= 400:
            logger.warning("Resend rechazó el envío (status=%s)", resp.status_code)
            raise PermanentDeliveryError(
                detail="El proveedor de correo rechazó el envío",
                channel="email",
                reason="rejected",
            )
