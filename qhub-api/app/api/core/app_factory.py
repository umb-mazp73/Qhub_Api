import logging
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.dependencies.Dependencies import (
    AppResources,
    RuntimeContainer,
    build_container,
)
from app.config.config import Settings, get_settings
from app.infrastructure.logging import configure_logging
from app.infrastructure.rate_limit.memory import MemoryRateLimiter
from app.api.core.error_handlers import install_error_handlers
from app.api.core.middleware import (
    account_key_from_request,
    create_rate_limit_middleware,
)
from app.api.core.security import _validar_access_token_propio
from app.api.routers.auth import router as auth_router
from app.api.routers.colas import router as colas_router
from app.api.routers.empresas import router as empresas_router
from app.api.routers.health import router as health_router
from app.api.routers.notificaciones import router as notifications_router
from app.api.routers.turnos import router as turns_router
from app.infrastructure.websocket.connection_manager import ConnectionManager
from app.api.routers.websocket import router as websocket_router

logger = logging.getLogger("qhub_api.bootstrap")


class ContainerFactory(Protocol):
    def __call__(
        self, settings: Settings, resources: AppResources
    ) -> RuntimeContainer: ...


def create_lifespan(container):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await container.start()
            yield
        finally:
            await container.stop()

    return lifespan


def create_app(
    settings: Settings | None = None,
    container_factory: ContainerFactory = build_container,
) -> FastAPI:
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings.DEBUG)
    if resolved_settings.APP_ENV.lower() == "production":
        for problem in resolved_settings.production_warnings():
            logger.warning("Configuración de producción: %s", problem)
    resources = AppResources(ConnectionManager(), MemoryRateLimiter())

    container = container_factory(resolved_settings, resources)
    app = FastAPI(
        title=resolved_settings.APP_NAME,
        debug=resolved_settings.DEBUG,
        lifespan=create_lifespan(container),
    )
    app.state.container = container

    origins = resolved_settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rate_limit = create_rate_limit_middleware(
        resources.rate_limiter,
        lambda: resolved_settings.RATE_LIMIT_REQUESTS_POR_MINUTO,
        lambda request: account_key_from_request(
            request, _validar_access_token_propio
        ),
        lambda: resolved_settings.RATE_LIMIT_AUTH_POR_MINUTO,
    )
    app.middleware("http")(rate_limit)
    install_error_handlers(app)

    for router in (
        auth_router,
        empresas_router,
        colas_router,
        turns_router,
        notifications_router,
        websocket_router,
        health_router,
    ):
        app.include_router(router)
    return app
