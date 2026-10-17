import asyncio
import logging

from app.application.errors import (
    PermanentDeliveryError,
    PermanentMessageError,
)
from app.infrastructure.messaging.rabbitmq.publishers import HEADER_INTENTOS

logger = logging.getLogger("qhub_api.rabbitmq.notification_worker")


class NotificationWorker:
    def __init__(
        self,
        rabbit,
        topology,
        deliver_use_case,
        parser,
        max_attempts: int,
        retry_seconds: int,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser mayor o igual a 1")
        if retry_seconds < 0:
            raise ValueError("retry_seconds no puede ser negativo")
        self._rabbit = rabbit
        self._topology = topology
        self._deliver = deliver_use_case
        self._parser = parser
        self._max_attempts = max_attempts
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task | None = None

    @property
    def task(self):
        return self._task

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._rabbit.enabled:
            return
        self._task = asyncio.create_task(
            self.run(), name="worker-notificaciones"
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _settle(self, message, action: str) -> None:
        if action == "ack":
            await message.ack()
        elif action == "reject":
            await message.reject(requeue=False)
        else:
            await message.nack(requeue=True)

    async def process_message(self, message) -> None:
        settled = False
        try:
            headers = message.headers or {}
            raw_attempt = headers.get(HEADER_INTENTOS, 0) or 0
            if type(raw_attempt) is not int:
                raise PermanentMessageError(
                    "Header de intentos inválido",
                    "type",
                    "notification_job",
                )
            attempt = raw_attempt
            if attempt < 0:
                raise PermanentMessageError(
                    "Header de intentos inválido",
                    "type",
                    "notification_job",
                )
            job = self._parser.parse(message.body)
            try:
                await self._deliver.deliver_job(job)
            except (PermanentMessageError, PermanentDeliveryError):
                await self._settle(message, "reject")
                settled = True
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt + 1 >= self._max_attempts:
                    await self._settle(message, "reject")
                    settled = True
                    return
                await asyncio.sleep(self._retry_seconds)
                try:
                    confirmed = await self._deliver_retry(job, attempt + 1)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    confirmed = False
                if not confirmed:
                    await self._settle(message, "nack")
                    settled = True
                    return
                await self._settle(message, "ack")
                settled = True
                return
            await self._settle(message, "ack")
            settled = True
        except PermanentMessageError:
            await self._settle(message, "reject")
            settled = True
        except asyncio.CancelledError:
            if not settled:
                try:
                    await asyncio.shield(message.nack(requeue=True))
                except Exception:
                    logger.warning("No se pudo reencolar durante cancelación")
            raise

    async def _deliver_retry(self, job, attempt: int) -> bool:
        publisher = getattr(self._deliver, "job_publisher", None)
        if publisher is None:
            publisher = getattr(self._deliver, "jobs", None)
        if publisher is None:
            publisher = getattr(self._deliver, "_jobs", None)
        if publisher is None:
            publisher = getattr(self, "_publisher", None)
        if publisher is None:
            raise RuntimeError("publisher de retry no disponible")
        return await publisher.publish(job, attempt=attempt)

    async def run(self) -> None:
        while True:
            declared = None
            try:
                declared = await self._topology.ensure_notification_queue()
                if declared is None:
                    return
                await declared.channel.set_qos(prefetch_count=10)
                async with declared.queue.iterator() as iterator:
                    async for message in iterator:
                        await self.process_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Worker de notificaciones caído; reintenta")
                await asyncio.sleep(5)
            finally:
                if declared is not None:
                    try:
                        await declared.channel.close()
                    except Exception:
                        pass

    handle_message = process_message
