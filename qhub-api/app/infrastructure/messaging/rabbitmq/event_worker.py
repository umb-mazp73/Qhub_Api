import asyncio
import logging

from app.application.errors import PermanentMessageError

logger = logging.getLogger("qhub_api.rabbitmq.event_worker")


class EventWorker:
    """Consume las colas dedicadas del broker (una por cola de negocio activa) y entrega
    cada evento al `sink` (que lo difunde a todas las instancias).

    La tabla `colas` es la fuente de verdad de qué colas existen: el barrido engancha las
    nuevas y suelta las que ya no están activas, borrando su cola del broker."""

    def __init__(
        self,
        source,
        sink,
        rabbit,
        topology,
        parser,
        scan_interval_seconds: int = 30,
    ) -> None:
        self._source = source
        self._sink = sink
        self._rabbit = rabbit
        self._topology = topology
        self._parser = parser
        self._scan_interval = scan_interval_seconds
        self._task: asyncio.Task | None = None
        # Por nombre de cola del broker. Un nombre se puede reusar (una cola eliminada y otra
        # nueva con el mismo nombre), así que además se recuerda de QUÉ cola es el consumidor.
        self._consumers: dict[str, asyncio.Task] = {}
        self._subscriptions: dict[str, object] = {}

    @property
    def task(self):
        return self._task

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._rabbit.enabled:
            return
        self._task = asyncio.create_task(self.run(), name="worker-eventos")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
        for child in self._consumers.values():
            child.cancel()
        await asyncio.gather(
            *([task] if task is not None else []),
            *self._consumers.values(),
            return_exceptions=True,
        )
        self._consumers.clear()
        self._subscriptions.clear()

    async def ensure_subscription(self, subscription) -> None:
        name = subscription.broker_queue_name
        current = self._consumers.get(name)
        if current is not None and not current.done():
            if self._subscriptions[name].queue_id == subscription.queue_id:
                return
            # El nombre lo tomó otra cola (la anterior se eliminó): el consumidor viejo
            # rechazaría sus eventos por no ser de su cola.
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)
        self._subscriptions[name] = subscription
        self._consumers[name] = asyncio.create_task(
            self._consume(subscription), name=f"worker-eventos-{name}"
        )

    async def drop_subscription(self, name: str) -> None:
        """Suelta el consumidor de una cola desactivada y borra su cola del broker si está
        vacía. Cada instancia lo hace al enterarse: borrar una cola ya borrada es inocuo."""
        task = self._consumers.pop(name, None)
        self._subscriptions.pop(name, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await self._topology.delete_business_queue(name)
        except Exception:
            logger.warning("No se pudo borrar la cola %s del broker", name)

    async def process_message(self, message, subscription) -> None:
        try:
            event = self._parser.parse(message.body, subscription)
            await self._sink.send(subscription.queue_id, event)
        except PermanentMessageError:
            await message.reject(requeue=False)
            return
        await message.ack()

    async def _still_active(self, subscription) -> bool:
        try:
            return any(
                item.queue_id == subscription.queue_id
                for item in await self._source.list_active()
            )
        except Exception:
            return True  # sin poder consultar la base, no se abandona un consumidor sano

    async def _consume(self, subscription) -> None:
        while True:
            declared = None
            try:
                declared = await self._topology.ensure_business_queue(subscription)
                if declared is None:
                    return
                async with declared.queue.iterator() as iterator:
                    async for message in iterator:
                        await self.process_message(message, subscription)
                # El broker canceló el consumo (otra instancia borró la cola al desactivarla).
                # Volver a declararla la resucitaría: solo se sigue si la cola sigue activa.
                await asyncio.sleep(5)
                if not await self._still_active(subscription):
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Consumidor de eventos caído; reintenta")
                await asyncio.sleep(5)
            finally:
                if declared is not None:
                    try:
                        await declared.channel.close()
                    except Exception:
                        pass

    async def run(self) -> None:
        while True:
            try:
                await self.scan()
                pause = self._scan_interval
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("No se pudo barrer las colas activas; se reintenta", exc_info=True)
                pause = min(5, self._scan_interval)  # un fallo no debe costar un intervalo entero
            await asyncio.sleep(pause)

    async def scan(self) -> None:
        """Engancha las colas activas nuevas y suelta (y borra del broker) las que dejaron
        de estarlo: un consumidor huérfano ocupa un canal, y su cola, uno de los 150 lugares
        del plan, que comparten todas las cuentas."""
        known = set(self._consumers)  # antes de leer: lo creado durante el barrido no se toca
        subscriptions = await self._source.list_active()
        active = {subscription.broker_queue_name for subscription in subscriptions}
        for subscription in subscriptions:
            await self.ensure_subscription(subscription)
        for name in known - active:
            await self.drop_subscription(name)
        for name, task in tuple(self._consumers.items()):
            if task.done():
                self._consumers.pop(name, None)
                self._subscriptions.pop(name, None)


class SubscribingQueueProvisioner:
    """Declara la cola dedicada en el broker Y engancha su consumidor en el acto.

    Sin esto, el consumidor de una cola recién creada esperaba al siguiente barrido (hasta
    30 s) y sus primeros eventos llegaban tarde a los WebSockets."""

    def __init__(self, topology, worker: EventWorker) -> None:
        self._topology = topology
        self._worker = worker

    async def ensure_queue(self, subscription) -> None:
        await self._topology.ensure_queue(subscription)
        if self._worker.task is not None:  # el worker solo corre si hay broker
            await self._worker.ensure_subscription(subscription)

    async def release_queue(self, subscription) -> None:
        if self._worker.task is not None:
            await self._worker.drop_subscription(subscription.broker_queue_name)
