import logging
from uuid import UUID

from app.domain.models import QueueEventEnvelope
from app.domain.interfaces.messaging import QueueEventFanoutPublisher, QueueEventSink

logger = logging.getLogger("qhub_api.delivery.eventos")


class QueueEventDistributor:
    """Destino de los eventos que salen de las colas dedicadas del broker.

    Una cola dedicada la consume UNA sola instancia (consumidores competidores), pero los
    WebSockets de esa cola pueden estar repartidos entre todas. Por eso el evento no se
    entrega aquí: se difunde a todas las instancias por un exchange fanout y cada una
    entrega a sus propios sockets. Si la difusión no está disponible, se entrega solo a
    los sockets de este proceso."""

    def __init__(self, fanout: QueueEventFanoutPublisher, local_sink: QueueEventSink) -> None:
        self._fanout = fanout
        self._local_sink = local_sink

    async def send(self, queue_id: UUID, event: QueueEventEnvelope) -> int:
        try:
            if await self._fanout.publish(event):
                return 0  # lo entregan las instancias al recibir la difusión
        except Exception:
            logger.warning("No se pudo difundir el evento de cola")
        return await self._local_sink.send(queue_id, event)
