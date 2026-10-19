"""EmailNotificationChannel: solo los tipos importantes envían correo, los demás se
omiten; sin correo del destinatario se omite con gracia; un fallo del sender no se propaga.
Sin dependencias extra: `python -m tests.test_email_channel` desde qhub-api/ (también pytest)."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.entities import Notificacion
from app.domain.enums import PropietarioTipo
from app.infrastructure.delivery.email_channel import EmailNotificationChannel
from app.domain.value_objects import OwnerId, PersonIdentity

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
OWNER = OwnerId(PropietarioTipo("usuario"), uuid4())


def notif(message: str = "Tu turno #7 fue cancelado.") -> Notificacion:
    return Notificacion(
        id=uuid4(),
        identity=PersonIdentity(OWNER, "ana"),
        turno_id=uuid4(),
        mensaje=message,
        leida=False,
        creada_en=NOW,
        clave_idempotencia=None,
    )


class StubSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, *, to, subject, html) -> None:
        self.calls.append({"to": to, "subject": subject, "html": html})


class RaisingSender:
    async def send(self, *, to, subject, html) -> None:
        raise RuntimeError("Brevo caído")


class StubResolver:
    def __init__(self, email) -> None:
        self._email = email

    async def email_for(self, identity) -> str | None:
        return self._email


def run(coro):
    return asyncio.run(coro)


def test_tipo_importante_con_correo_envia_una_vez():
    sender = StubSender()
    channel = EmailNotificationChannel(sender, StubResolver("ana@example.com"))
    run(channel.deliver(notif(), "turno_cancelado"))
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["to"] == "ana@example.com"
    assert call["subject"] == "Qhub · Tu turno fue cancelado"
    assert "Qhub" in call["html"]
    assert "Tu turno #7 fue cancelado." in call["html"]


def test_tipo_no_importante_se_omite():
    for tipo in ("turno_pospuesto", "turno_creado"):
        sender = StubSender()
        channel = EmailNotificationChannel(sender, StubResolver("ana@example.com"))
        run(channel.deliver(notif(), tipo))
        assert sender.calls == []


def test_sin_correo_se_omite_con_gracia():
    sender = StubSender()
    channel = EmailNotificationChannel(sender, StubResolver(None))
    run(channel.deliver(notif(), "turno_llamado"))  # no debe lanzar
    assert sender.calls == []


def test_fallo_del_sender_no_se_propaga():
    channel = EmailNotificationChannel(RaisingSender(), StubResolver("ana@example.com"))
    run(channel.deliver(notif(), "recordatorio"))  # no debe lanzar


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
