import logging
from dataclasses import dataclass

import aio_pika
from aiormq.exceptions import ChannelPreconditionFailed

from app.application.errors import BrokerUnavailable
from app.domain.value_objects import QueueSubscription

logger = logging.getLogger("qhub_api.rabbitmq.topology")

EXCHANGE_NAME = "app.eventos"
DLX_NAME = "app.dlx"
DLQ_NAME = "app.dlq"
NOTIF_QUEUE_NAME = "app.notificaciones"
NOTIF_ROUTING_KEY = "notificacion"
NOTIF_DIFUSION_EXCHANGE = "app.notificaciones.difusion"
EVENTOS_DIFUSION_EXCHANGE = "app.eventos.difusion"


@dataclass(frozen=True, slots=True)
class DeclaredQueue:
    channel: object
    exchange: object
    queue: object


class RabbitTopology:
    def __init__(
        self,
        rabbit,
        *,
        exchange_name: str = EXCHANGE_NAME,
        dlx_name: str = DLX_NAME,
        dlq_name: str = DLQ_NAME,
        notification_queue_name: str = NOTIF_QUEUE_NAME,
        fanout_exchange_name: str = NOTIF_DIFUSION_EXCHANGE,
        events_fanout_exchange_name: str = EVENTOS_DIFUSION_EXCHANGE,
        logger_: logging.Logger = logger,
    ) -> None:
        self._rabbit = rabbit
        self.exchange_name = exchange_name
        self.dlx_name = dlx_name
        self.dlq_name = dlq_name
        self.notification_queue_name = notification_queue_name
        self.fanout_exchange_name = fanout_exchange_name
        self.events_fanout_exchange_name = events_fanout_exchange_name
        self._logger = logger_

    async def _exchange(self, channel):
        return await channel.declare_exchange(
            self.exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
        )

    async def _dead_letter(self, channel) -> None:
        dlx = await channel.declare_exchange(
            self.dlx_name, aio_pika.ExchangeType.FANOUT, durable=True
        )
        dlq = await channel.declare_queue(self.dlq_name, durable=True)
        await dlq.bind(dlx)

    async def _close_safely(self, channel) -> None:
        try:
            await channel.close()
        except Exception:
            pass

    async def _fresh_channel(self, failed_channel):
        await self._close_safely(failed_channel)
        connection = getattr(failed_channel, "connection", None)
        if connection is not None:
            return await connection.channel()
        channel = await self._rabbit.open_channel()
        if channel is None:
            raise BrokerUnavailable("open_rabbitmq_channel")
        return channel

    async def _declare(
        self,
        channel,
        exchange,
        queue_name: str,
        routing_key: str,
        operation: str,
    ) -> DeclaredQueue:
        active = channel
        try:
            queue = await channel.declare_queue(
                queue_name,
                durable=True,
                arguments={"x-dead-letter-exchange": self.dlx_name},
            )
        except ChannelPreconditionFailed:
            active = await self._fresh_channel(channel)
            try:
                exchange = await self._exchange(active)
                queue = await active.declare_queue(queue_name, durable=True)
                await queue.bind(exchange, routing_key=routing_key)
            except Exception as exc:
                await self._close_safely(active)
                raise BrokerUnavailable(operation) from exc
            self._logger.warning("Cola %s: legacy sin DLX", queue_name)
            return DeclaredQueue(active, exchange, queue)
        except Exception as exc:
            await self._close_safely(active)
            raise BrokerUnavailable(operation) from exc
        try:
            await queue.bind(exchange, routing_key=routing_key)
        except Exception as exc:
            await self._close_safely(active)
            raise BrokerUnavailable(operation) from exc
        return DeclaredQueue(active, exchange, queue)

    async def ensure_business_queue(
        self, subscription: QueueSubscription
    ) -> DeclaredQueue | None:
        channel = await self._rabbit.open_channel()
        if channel is None:
            return None
        try:
            exchange = await self._exchange(channel)
            await self._dead_letter(channel)
        except Exception as exc:
            await self._close_safely(channel)
            raise BrokerUnavailable("ensure_business_queue") from exc
        return await self._declare(
            channel,
            exchange,
            subscription.broker_queue_name,
            str(subscription.queue_id),
            "ensure_business_queue",
        )

    async def delete_business_queue(self, queue_name: str) -> None:
        """Borra la cola dedicada SOLO si está vacía: si aún tiene eventos sin consumir, se
        conserva (la borrará otro barrido). Sin broker no hace nada."""
        channel = await self._rabbit.open_channel()
        if channel is None:
            return
        try:
            await channel.queue_delete(queue_name, if_empty=True)
        except Exception:
            self._logger.info("Cola %s no se borró (no está vacía o ya no existe)", queue_name)
        finally:
            await self._close_safely(channel)

    async def ensure_queue(self, subscription: QueueSubscription) -> None:
        declared = await self.ensure_business_queue(subscription)
        if declared is not None:
            await self._close_safely(declared.channel)

    async def ensure_notification_queue(
        self, *, publisher_confirms: bool = False
    ) -> DeclaredQueue | None:
        channel = (
            await self._rabbit.open_channel(publisher_confirms=True)
            if publisher_confirms
            else await self._rabbit.open_channel()
        )
        if channel is None:
            return None
        try:
            exchange = await self._exchange(channel)
            await self._dead_letter(channel)
        except Exception as exc:
            await self._close_safely(channel)
            raise BrokerUnavailable("ensure_notification_queue") from exc
        return await self._declare(
            channel,
            exchange,
            self.notification_queue_name,
            NOTIF_ROUTING_KEY,
            "ensure_notification_queue",
        )

    async def ensure_notification_queue_on(
        self, channel, exchange
    ):
        declared = await self._declare(
            channel,
            exchange,
            self.notification_queue_name,
            NOTIF_ROUTING_KEY,
            "ensure_notification_queue",
        )
        return declared.queue

    async def declare_fanout(self, channel, exchange_name: str | None = None):
        """Exchange fanout de difusión entre instancias (por defecto, el de notificaciones)."""
        return await channel.declare_exchange(
            exchange_name or self.fanout_exchange_name,
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )

    async def declare_events_fanout(self, channel):
        return await self.declare_fanout(channel, self.events_fanout_exchange_name)

    async def ensure_events_fanout_queue(self) -> DeclaredQueue | None:
        return await self.ensure_fanout_queue(self.events_fanout_exchange_name)

    async def ensure_fanout_queue(
        self, exchange_name: str | None = None
    ) -> DeclaredQueue | None:
        """Cola EXCLUSIVA y efímera de ESTA instancia, ligada a un exchange fanout: todas
        las instancias reciben cada mensaje y lo entregan a sus propios WebSockets."""
        channel = await self._rabbit.open_channel()
        if channel is None:
            return None
        try:
            exchange = await self.declare_fanout(channel, exchange_name)
            queue = await channel.declare_queue(
                exclusive=True, auto_delete=True, durable=False
            )
            await queue.bind(exchange)
            return DeclaredQueue(channel, exchange, queue)
        except Exception as exc:
            await self._close_safely(channel)
            raise BrokerUnavailable("ensure_fanout_queue") from exc
