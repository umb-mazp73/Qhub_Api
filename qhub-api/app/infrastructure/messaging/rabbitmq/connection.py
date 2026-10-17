import asyncio
from collections.abc import Callable

import aio_pika

from app.application.errors import BrokerUnavailable


class RabbitConnectionManager:
    def __init__(
        self,
        url: str,
        connect: Callable = aio_pika.connect_robust,
    ) -> None:
        self._url = url
        self._connect = connect
        self._connection = None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    @property
    def connection(self):
        return self._connection

    async def get_connection(self):
        if not self._url:
            return None
        async with self._lock:
            if self._connection is None or self._connection.is_closed:
                try:
                    self._connection = await self._connect(self._url)
                except Exception as exc:
                    raise BrokerUnavailable("connect_rabbitmq") from exc
            return self._connection

    async def open_channel(self, *, publisher_confirms: bool = False):
        connection = await self.get_connection()
        if connection is None:
            return None
        try:
            return await connection.channel(
                publisher_confirms=publisher_confirms
            )
        except TypeError:
            return await connection.channel()
        except Exception as exc:
            raise BrokerUnavailable("open_rabbitmq_channel") from exc

    async def close(self) -> None:
        async with self._lock:
            connection = self._connection
            self._connection = None
        if connection is not None and not connection.is_closed:
            await connection.close()
