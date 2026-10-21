import asyncio
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

from supabase import AsyncClient
from supabase.lib.client_options import AsyncClientOptions

from app.application.errors import PersistenceUnavailable

logger = logging.getLogger("qhub_api.persistence.supabase")


class ClientState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    STARTED = "started"
    CLOSING = "closing"
    CLOSED = "closed"


class SupabaseClientOwner:
    def __init__(
        self,
        url: str,
        key: str,
        *,
        options: AsyncClientOptions | None = None,
        client: AsyncClient | None = None,
        client_factory: Callable[[str, str, AsyncClientOptions | None], AsyncClient] = AsyncClient,
    ) -> None:
        self._url = url
        self._key = key
        self._options = options
        self._client_factory = client_factory
        self._client = client
        self._owns_client = client is None
        self._state = ClientState.STARTED if client is not None else ClientState.NEW
        self._lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> ClientState:
        return self._state

    @property
    def client(self) -> AsyncClient | None:
        return self._client

    async def start(self) -> None:
        failed = False
        async with self._lock:
            if self._state is ClientState.STARTED:
                return
            if self._state in {ClientState.STARTING, ClientState.CLOSING}:
                raise PersistenceUnavailable(operation="start_supabase")
            if self._state is ClientState.CLOSED:
                self._state = ClientState.NEW
                self._close_task = None
            if not self._url or not self._key:
                self._state = ClientState.STARTED
                return

            self._state = ClientState.STARTING
            options = self._options or AsyncClientOptions()
            client = self._client_factory(self._url, self._key, options)
            self._client = client
            self._owns_client = True
            try:
                session = await client.auth.get_session()
                if hasattr(client, "options") and hasattr(client, "_get_auth_headers"):
                    access_token = (
                        client._create_auth_header(session.access_token) if session else None
                    )
                    client.options.headers.update(client._get_auth_headers(access_token))
            except Exception:
                failed = True
                logger.warning("No se pudo iniciar la sesión de Supabase")
            else:
                self._state = ClientState.STARTED

        if failed:
            await self.close()

    def require_client(self) -> AsyncClient:
        if self._state is not ClientState.STARTED or self._client is None:
            raise PersistenceUnavailable(operation="require_supabase_client")
        return self._client

    async def close(self) -> None:
        async with self._lock:
            if self._state is ClientState.CLOSED:
                return
            if self._state is ClientState.CLOSING:
                task = self._close_task
            else:
                self._state = ClientState.CLOSING
                client = self._client
                self._client = None
                task = asyncio.create_task(
                    self._finish_close(client, self._owns_client),
                    name="close-supabase-client",
                )
                self._close_task = task
        if task is not None:
            await asyncio.shield(task)

    async def _finish_close(self, client: AsyncClient | None, owned: bool) -> None:
        try:
            if client is not None and owned:
                await asyncio.gather(
                    self._close_one("realtime", client.realtime.close),
                    self._close_one("postgrest", client.postgrest.aclose),
                    self._close_one("auth", client.auth.close),
                    return_exceptions=True,
                )
        finally:
            async with self._lock:
                self._state = ClientState.CLOSED

    async def _close_one(self, name: str, close: Callable[[], Any]) -> None:
        try:
            result = close()
            if hasattr(result, "__await__"):
                await result
        except Exception:
            logger.warning("No se pudo cerrar el recurso Supabase %s", name)
