import json
import logging
from datetime import date, datetime
from uuid import UUID

import aio_pika
from pydantic import BaseModel

from app.application.errors import BrokerUnavailable
from app.domain.models import (
    FanoutNotification,
    NotificationJob,
    QueueEvent,
    QueueEventEnvelope,
    freeze_json,
)
from app.domain.interfaces.messaging import QueueEventSink, TurnEventPublisher
from app.domain.enums import PropietarioTipo, TurnoEstado
from app.infrastructure.messaging.rabbitmq.topology import NOTIF_ROUTING_KEY

logger = logging.getLogger("qhub_api.rabbitmq.publishers")

HEADER_INTENTOS = "qhub-intentos"


class TurnPayload(BaseModel):
    id: UUID
    cola_id: UUID
    propietario_tipo: PropietarioTipo
    propietario_id: UUID
    propietario_nombre: str
    usuario_id: str
    franja_inicio: datetime
    franja_fecha: date
    programado: bool
    numero: int
    estado: TurnoEstado
    posicion: int
    hora_creacion: datetime
    hora_atencion: datetime | None
    hora_finalizacion: datetime | None
    agente_id: str | None
    recordatorio_enviado_en: datetime | None = None


class QueueEventMessage(BaseModel):
    tipo: str
    cola_id: UUID
    payload: TurnPayload

    @classmethod
    def from_event(cls, event: QueueEvent) -> "QueueEventMessage":
        turn = event.payload
        return cls(
            tipo=event.event_type,
            cola_id=event.queue_id,
            payload=TurnPayload(
                id=turn.id,
                cola_id=turn.cola_id,
                propietario_tipo=turn.owner.tipo,
                propietario_id=turn.owner.id,
                propietario_nombre=turn.propietario_nombre,
                usuario_id=turn.usuario_id,
                franja_inicio=turn.franja_inicio,
                franja_fecha=turn.franja_fecha,
                programado=turn.programado,
                numero=turn.numero,
                estado=turn.estado,
                posicion=turn.posicion,
                hora_creacion=turn.hora_creacion,
                hora_atencion=turn.hora_atencion,
                hora_finalizacion=turn.hora_finalizacion,
                agente_id=turn.agente_id,
                recordatorio_enviado_en=turn.recordatorio_enviado_en,
            ),
        )

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def envelope_from_event(event: QueueEvent) -> QueueEventEnvelope:
    """El mismo sobre que produce el parser al leer el mensaje del broker, para poder
    entregar un evento localmente sin pasar por RabbitMQ."""
    wire = freeze_json(QueueEventMessage.from_event(event).to_wire())
    return QueueEventEnvelope(event.queue_id, event.event_type, wire["payload"], wire)


def notification_job_to_wire(job: NotificationJob) -> dict[str, object]:
    return {
        "clave": str(job.key),
        "tipo": job.notice_type,
        "propietario_tipo": job.identity.owner.tipo.value,
        "propietario_id": str(job.identity.owner.id),
        "usuario_id": job.identity.usuario_id,
        "turno_id": str(job.turn_id) if job.turn_id else None,
        "mensaje": job.message,
    }


def fanout_to_wire(message: FanoutNotification) -> dict[str, object]:
    return {
        "propietario_tipo": message.identity.owner.tipo.value,
        "propietario_id": str(message.identity.owner.id),
        "usuario_id": message.identity.usuario_id,
        "mensaje": message.message.to_wire(),
    }


async def _close_safely(channel) -> None:
    try:
        await channel.close()
    except Exception:
        pass


class RabbitTurnEventPublisher(TurnEventPublisher):
    def __init__(self, rabbit, topology) -> None:
        self._rabbit = rabbit
        self._topology = topology

    async def publish(self, event: QueueEvent) -> bool:
        """True si el evento quedó en el broker; False si no hay broker configurado."""
        channel = await self._rabbit.open_channel()
        if channel is None:
            return False
        try:
            exchange = await channel.declare_exchange(
                self._topology.exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            body = json.dumps(
                QueueEventMessage.from_event(event).to_wire()
            ).encode("utf-8")
            await exchange.publish(
                aio_pika.Message(body=body), routing_key=str(event.queue_id)
            )
            return True
        except Exception as exc:
            raise BrokerUnavailable("publish_turn_event") from exc
        finally:
            await _close_safely(channel)


class RabbitNotificationJobPublisher:
    def __init__(self, rabbit, topology) -> None:
        self._rabbit = rabbit
        self._topology = topology

    async def publish(
        self, job: NotificationJob, attempt: int = 0
    ) -> bool:
        if not self._rabbit.enabled:
            return False
        declared = None
        try:
            declared = await self._topology.ensure_notification_queue(
                publisher_confirms=True
            )
            if declared is None:
                return False
            confirmation = await declared.exchange.publish(
                aio_pika.Message(
                    body=json.dumps(notification_job_to_wire(job)).encode("utf-8"),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers={HEADER_INTENTOS: attempt},
                    content_type="application/json",
                ),
                routing_key=NOTIF_ROUTING_KEY,
            )
            return confirmation is not False
        except Exception:
            return False
        finally:
            if declared is not None:
                await _close_safely(declared.channel)


class RabbitFanoutPublisher:
    def __init__(self, rabbit, topology) -> None:
        self._rabbit = rabbit
        self._topology = topology

    async def publish(self, message: FanoutNotification) -> bool:
        if not self._rabbit.enabled:
            return False
        channel = None
        try:
            channel = await self._rabbit.open_channel(
                publisher_confirms=True
            )
            if channel is None:
                return False
            exchange = await self._topology.declare_fanout(channel)
            confirmation = await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(fanout_to_wire(message)).encode("utf-8"),
                    content_type="application/json",
                ),
                routing_key="",
            )
            return confirmation is not False
        except Exception:
            return False
        finally:
            if channel is not None:
                await _close_safely(channel)


class RabbitQueueEventFanoutPublisher:
    """Reparte un evento de cola a TODAS las instancias (cada una entrega a sus sockets)."""

    def __init__(self, rabbit, topology) -> None:
        self._rabbit = rabbit
        self._topology = topology

    async def publish(self, event: QueueEventEnvelope) -> bool:
        if not self._rabbit.enabled:
            return False
        channel = None
        try:
            channel = await self._rabbit.open_channel(publisher_confirms=True)
            if channel is None:
                return False
            exchange = await self._topology.declare_events_fanout(channel)
            confirmation = await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(event.to_wire()).encode("utf-8"),
                    content_type="application/json",
                ),
                routing_key="",
            )
            return confirmation is not False
        except Exception:
            return False
        finally:
            if channel is not None:
                await _close_safely(channel)


class ResilientTurnEventPublisher(TurnEventPublisher):
    """Publica en el broker y, si no se puede (sin RABBITMQ_URL o broker caído), entrega
    el evento a los WebSockets de ESTE proceso: un evento que alguien está escuchando
    aquí no debería perderse solo porque el broker no responde."""

    def __init__(self, primary: TurnEventPublisher, local_sink: QueueEventSink) -> None:
        self._primary = primary
        self._local_sink = local_sink

    async def publish(self, event: QueueEvent) -> bool:
        try:
            if await self._primary.publish(event):
                return True
        except Exception:
            logger.warning("No se pudo publicar el evento en el broker; se entrega en este proceso")
        try:
            await self._local_sink.send(event.queue_id, envelope_from_event(event))
        except Exception:
            logger.warning("No se pudo entregar el evento localmente")
        return False
