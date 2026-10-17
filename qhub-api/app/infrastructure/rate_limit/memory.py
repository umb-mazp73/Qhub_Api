import time
from collections import defaultdict, deque
from collections.abc import Callable

_PURGE_EVERY = 1000  # llamadas entre limpiezas de claves que ya no tienen actividad


class MemoryRateLimiter:
    """Ventana deslizante en memoria. Vive en el proceso: con varias instancias el tope
    efectivo es por instancia (no compartido)."""

    def __init__(
        self,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_seconds = window_seconds
        self._clock = clock
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def allow(
        self,
        account_key: str,
        requests_per_minute: int,
        now: float | None = None,
    ) -> bool:
        if requests_per_minute <= 0:
            return True

        current = self._clock() if now is None else now
        self._calls += 1
        if self._calls % _PURGE_EVERY == 0:
            self._purge(current)
        timestamps = self._timestamps[account_key]
        while timestamps and current - timestamps[0] > self._window_seconds:
            timestamps.popleft()
        if len(timestamps) >= requests_per_minute:
            return False
        timestamps.append(current)
        return True

    def _purge(self, current: float) -> None:
        """Sin esto, cada IP o cuenta que alguna vez pasó dejaría una entrada para siempre."""
        for key in [
            key
            for key, stamps in self._timestamps.items()
            if not stamps or current - stamps[-1] > self._window_seconds
        ]:
            del self._timestamps[key]
