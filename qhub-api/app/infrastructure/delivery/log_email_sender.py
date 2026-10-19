import logging

logger = logging.getLogger("qhub_api.delivery.email")


class LogEmailSender:
    """Fallback sin BREVO_API_KEY: deja constancia en el log (sin el cuerpo ni la api-key).

    Permite que el flujo de recuperación corra de punta a punta sin un proveedor real."""

    async def send(self, *, to: str, subject: str, html: str) -> None:
        logger.info("Correo entregado (canal: log) asunto=%s", subject)
