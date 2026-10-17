import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.application.use_cases.barridos import SweepUseCases

logger = logging.getLogger("qhub_api.scheduling.sweeps")


class ScheduledSweepWorker:
    def __init__(
        self,
        sweeps: SweepUseCases,
        interval_seconds: int,
        *,
        enabled: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds debe ser mayor que cero")
        self._sweeps = sweeps
        self._interval_seconds = interval_seconds
        self._enabled = enabled
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    async def start(self) -> None:
        if not self._enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.run(), name="tareas-programadas")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def run(self) -> None:
        while True:
            try:
                await self._sweeps.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Falló una pasada de barridos; se reintentará")
            await self._sleep(self._interval_seconds)
