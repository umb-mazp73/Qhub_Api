from typing import Protocol


class EmailSender(Protocol):
    """Envío de correo transaccional.

    Contrato: éxito = retorno silencioso. Fallo de envío NO recuperable (destino inválido,
    4xx del proveedor) = levantar PermanentDeliveryError(channel="email", reason="rejected").
    El caso de uso que lo invoca (AuthUseCases.send_reset_email) corre dentro de un
    BackgroundTask y consume el error; nunca escapa al cliente.
    """

    async def send(self, *, to: str, subject: str, html: str) -> None: ...
