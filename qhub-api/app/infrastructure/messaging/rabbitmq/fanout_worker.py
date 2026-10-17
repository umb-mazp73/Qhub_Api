import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.application.errors import PermanentMessageError

logger = logging.getLogger("qhub_api.rabbitmq.fanout_worker")


class FanoutWorker:
    """Consume la cola exclusiva de ESTA instancia en un exchange fanout y entrega cada
    mensaje a los WebSockets locales. Sirve tanto para las notificaciones personales como
    para los eventos de cola: lo único que cambia es la cola, el parser y el destino."""

    def __init__(
        self,
        rabbit,
        ensure_queue: Callable[[], Awaitable],
        parser,
        deliver: Callable[[object], Awaitable[int]],
        name: str = "worker-difusion",
    ) -> None:
        self._rabbit = rabbit
        self._ensure_queue = ensure_queue
        self._parser = parser
        self._deliver = deliver
        self._name = name
        self._task: asyncio.Task | None = None

    @property
    def task(self):
        return self._task

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._rabbit.enabled:
            return
        self._task = asyncio.create_task(self.run(), name=self._name)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def process_message(self, message) -> int:
        try:
            parsed = self._parser.parse(message.body)
        except PermanentMessageError:
            await message.ack()
            return 0
        try:
            delivered = await self._deliver(parsed)
        except Exception:
            logger.warning("No se pudo entregar la difusión local (%s)", self._name)
            delivered = 0
        await message.ack()
        return delivered

    async def run(self) -> None:
        while True:
            declared = None
            try:
                declared = await self._ensure_queue()
                if declared is None:
                    return
                async with declared.queue.iterator() as iterator:
                    async for message in iterator:
                        await self.process_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Worker de difusión caído; reintenta (%s)", self._name)
                await asyncio.sleep(5)
            finally:
                if declared is not None:
                    try:
                        await declared.channel.close()
                    except Exception:
                        pass
