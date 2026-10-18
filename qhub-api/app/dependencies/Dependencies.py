import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum

from dependency_injector import containers, providers

from app.application.services.delivery_dispatcher import DeliveryDispatcher
from app.application.services.live_websocket_delivery import LiveWebSocketDeliveryChannel
from app.application.services.queue_event_distribution import QueueEventDistributor
from app.application.use_cases.auth import AuthUseCases
from app.application.use_cases.barridos import SweepUseCases
from app.application.use_cases.colas import QueueUseCases
from app.application.use_cases.empresas import EmpresaUseCases
from app.application.use_cases.notificaciones import NotificationUseCases
from app.application.use_cases.turnos import TurnUseCases
from app.config.config import Settings
from app.infrastructure.clock import SystemClock, UuidGenerator
from app.infrastructure.messaging.rabbitmq.connection import RabbitConnectionManager
from app.infrastructure.delivery.log_channel import LogNotificationChannel
from app.infrastructure.messaging.rabbitmq.event_worker import EventWorker, SubscribingQueueProvisioner
from app.infrastructure.messaging.rabbitmq.fanout_worker import FanoutWorker
from app.infrastructure.messaging.rabbitmq.notification_worker import NotificationWorker
from app.infrastructure.messaging.rabbitmq.parsers import (
    FanoutNotificationParser,
    FanoutQueueEventParser,
    NotificationJobParser,
    RabbitQueueEventParser,
)
from app.infrastructure.messaging.rabbitmq.publishers import (
    RabbitFanoutPublisher,
    RabbitNotificationJobPublisher,
    RabbitQueueEventFanoutPublisher,
    RabbitTurnEventPublisher,
    ResilientTurnEventPublisher,
)
from app.infrastructure.messaging.rabbitmq.topology import RabbitTopology
from app.infrastructure.persistence.supabase.account_repository import SupabaseAccountRepository
from app.infrastructure.persistence.supabase.client import SupabaseClientOwner
from app.infrastructure.persistence.supabase.empresa_repository import SupabaseEmpresaRepository
from app.infrastructure.persistence.supabase.notification_repository import (
    SupabaseNotificationPersistence,
    SupabaseNotificationRepository,
)
from app.infrastructure.persistence.supabase.queue_repository import SupabaseQueueRepository
from app.infrastructure.persistence.supabase.subscription_source import (
    SupabaseActiveQueueSubscriptionSource,
)
from app.infrastructure.persistence.supabase.sweep_repository import SupabaseSweepRepository
from app.infrastructure.persistence.supabase.turn_repository import SupabaseTurnRepository
from app.infrastructure.rate_limit.memory import MemoryRateLimiter
from app.infrastructure.scheduling.sweep_worker import ScheduledSweepWorker
from app.infrastructure.security.api_keys import ApiKeyCodec
from app.infrastructure.security.bcrypt_hasher import BcryptPasswordHasher
from app.infrastructure.security.jwt_tokens import JwtAccessTokenService
from app.infrastructure.websocket.connection_manager import ConnectionManager

logger = logging.getLogger("qhub_api.bootstrap")


@dataclass(frozen=True, slots=True)
class AppResources:
    websocket_manager: ConnectionManager
    rate_limiter: MemoryRateLimiter


class ContainerState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"


class _SupabaseProviderProxy:
    def __init__(self, owner: SupabaseClientOwner) -> None:
        self._owner = owner

    def __getattr__(self, name: str):
        return getattr(self._owner.require_client(), name)


def _select_channels(settings: Settings, live_delivery) -> tuple[list, set[str]]:
    """Parsea NOTIFICACIONES_CANALES preservando orden, dedup y el warning de canal
    desconocido. Aquí se engancha un canal real (push, email, SMS)."""
    channels: list = []
    seen: set[str] = set()
    for configured in settings.NOTIFICACIONES_CANALES.split(","):
        name = configured.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        if name == "websocket":
            channels.append(live_delivery)
        elif name == "log":
            channels.append(LogNotificationChannel())
        else:
            logger.warning("Canal de notificación desconocido: %r", name)
    return channels, seen


class Dependencies(containers.DeclarativeContainer):
    """Composition root con dependency-injector.

    Settings, recursos de proceso y conexiones de infraestructura (Supabase, RabbitMQ) son
    Singleton: una conexión por proceso, compartida por todas las requests. Utilidades sin
    estado, repositorios y publishers son Factory. Los recursos mutables de proceso
    (websocket_manager, rate_limiter) se sobreescriben por app con el AppResources que
    construye `create_app`, para aislar una app de otra.
    """

    settings: providers.Singleton[Settings] = providers.Singleton(Settings)

    # Recursos de proceso con estado mutable (una instancia por app; app_factory los
    # sobreescribe con el AppResources que ya construye por app).
    websocket_manager: providers.Singleton[ConnectionManager] = providers.Singleton(ConnectionManager)
    rate_limiter: providers.Singleton[MemoryRateLimiter] = providers.Singleton(MemoryRateLimiter)

    # Conexiones de infraestructura (una por proceso).
    supabase: providers.Singleton[SupabaseClientOwner] = providers.Singleton(
        SupabaseClientOwner,
        settings.provided.SUPABASE_URL,
        settings.provided.SUPABASE_KEY,
    )
    client = providers.Singleton(_SupabaseProviderProxy, supabase)
    rabbit: providers.Singleton[RabbitConnectionManager] = providers.Singleton(
        RabbitConnectionManager,
        settings.provided.RABBITMQ_URL,
    )
    topology: providers.Singleton[RabbitTopology] = providers.Singleton(
        RabbitTopology,
        rabbit,
        exchange_name=settings.provided.RABBITMQ_EXCHANGE,
        dlx_name=settings.provided.RABBITMQ_DLX,
        dlq_name=settings.provided.RABBITMQ_DLQ,
        notification_queue_name=settings.provided.RABBITMQ_NOTIFICACIONES_QUEUE,
        fanout_exchange_name=settings.provided.RABBITMQ_NOTIFICACIONES_FANOUT,
        events_fanout_exchange_name=settings.provided.RABBITMQ_EVENTOS_FANOUT,
    )

    # Utilidades sin estado compartido.
    clock: providers.Factory[SystemClock] = providers.Factory(SystemClock)
    ids: providers.Factory[UuidGenerator] = providers.Factory(UuidGenerator)
    api_keys: providers.Factory[ApiKeyCodec] = providers.Factory(ApiKeyCodec)
    password_hasher: providers.Factory[BcryptPasswordHasher] = providers.Factory(BcryptPasswordHasher)
    tokens: providers.Factory[JwtAccessTokenService] = providers.Factory(
        JwtAccessTokenService,
        settings.provided.JWT_SECRET_KEY,
        settings.provided.JWT_ACCESS_TOKEN_EXPIRE_MINUTOS,
    )

    # Publishers (sin estado compartido, se construyen sobre rabbit+topology).
    events: providers.Factory[ResilientTurnEventPublisher] = providers.Factory(
        ResilientTurnEventPublisher,
        providers.Factory(RabbitTurnEventPublisher, rabbit, topology),
        websocket_manager,
    )
    jobs: providers.Factory[RabbitNotificationJobPublisher] = providers.Factory(
        RabbitNotificationJobPublisher, rabbit, topology
    )
    fanout: providers.Factory[RabbitFanoutPublisher] = providers.Factory(
        RabbitFanoutPublisher, rabbit, topology
    )
    events_fanout: providers.Factory[RabbitQueueEventFanoutPublisher] = providers.Factory(
        RabbitQueueEventFanoutPublisher, rabbit, topology
    )
    live_delivery: providers.Factory[LiveWebSocketDeliveryChannel] = providers.Factory(
        LiveWebSocketDeliveryChannel, fanout, websocket_manager
    )

    # Repositorios (Factory sobre el proxy de cliente Supabase).
    accounts: providers.Factory[SupabaseAccountRepository] = providers.Factory(
        SupabaseAccountRepository, client
    )
    empresas_repository: providers.Factory[SupabaseEmpresaRepository] = providers.Factory(
        SupabaseEmpresaRepository, client
    )
    queues_repository: providers.Factory[SupabaseQueueRepository] = providers.Factory(
        SupabaseQueueRepository, client
    )
    turns_repository: providers.Factory[SupabaseTurnRepository] = providers.Factory(
        SupabaseTurnRepository, client
    )
    notification_repository: providers.Factory[SupabaseNotificationRepository] = providers.Factory(
        SupabaseNotificationRepository, client
    )
    notification_persistence: providers.Factory[SupabaseNotificationPersistence] = providers.Factory(
        SupabaseNotificationPersistence, client
    )
    sweep_repository: providers.Factory[SupabaseSweepRepository] = providers.Factory(
        SupabaseSweepRepository, client
    )
    subscription_source: providers.Factory[SupabaseActiveQueueSubscriptionSource] = providers.Factory(
        SupabaseActiveQueueSubscriptionSource, client
    )

    # Use cases y servicios de aplicación (Factory). queues/notifications/turns/sweeps se
    # ensamblan en build_container porque dependen de los workers o de la selección de
    # canales en runtime.
    auth: providers.Factory[AuthUseCases] = providers.Factory(
        AuthUseCases,
        accounts,
        password_hasher,
        api_keys,
        tokens,
        clock,
    )
    empresas: providers.Factory[EmpresaUseCases] = providers.Factory(
        EmpresaUseCases, empresas_repository, api_keys, clock
    )

    # Parsers de los workers.
    queue_event_parser: providers.Factory[RabbitQueueEventParser] = providers.Factory(
        RabbitQueueEventParser
    )
    notification_job_parser: providers.Factory[NotificationJobParser] = providers.Factory(
        NotificationJobParser
    )
    fanout_notification_parser: providers.Factory[FanoutNotificationParser] = providers.Factory(
        FanoutNotificationParser
    )
    fanout_event_parser: providers.Factory[FanoutQueueEventParser] = providers.Factory(
        FanoutQueueEventParser
    )


@dataclass(slots=True)
class RuntimeContainer:
    settings: Settings
    supabase: SupabaseClientOwner
    rabbit: RabbitConnectionManager
    auth: AuthUseCases
    empresas: EmpresaUseCases
    queues: QueueUseCases
    turns: TurnUseCases
    notifications: NotificationUseCases
    sweeps: SweepUseCases
    event_worker: EventWorker
    notification_worker: NotificationWorker
    fanout_worker: FanoutWorker
    event_fanout_worker: FanoutWorker
    sweep_worker: ScheduledSweepWorker
    resources: AppResources
    _state: ContainerState = field(default=ContainerState.NEW, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def state(self) -> ContainerState:
        return self._state

    async def start(self) -> None:
        async with self._lock:
            if self._state is ContainerState.STARTED:
                return
            if self._state not in {ContainerState.NEW, ContainerState.STOPPED}:
                raise RuntimeError(f"No se puede iniciar el container en estado {self._state.value}")
            self._state = ContainerState.STARTING
            if hasattr(self.supabase, "_url"):
                self.supabase._url = self.settings.SUPABASE_URL
                self.supabase._key = self.settings.SUPABASE_KEY
            if hasattr(self.rabbit, "_url"):
                self.rabbit._url = self.settings.RABBITMQ_URL
            if hasattr(self.sweep_worker, "_enabled"):
                self.sweep_worker._enabled = bool(
                    self.settings.SUPABASE_URL and self.settings.SUPABASE_KEY
                )
            started: list[object] = []
            try:
                await self.supabase.start()
                started.append(self.supabase)
                for worker in (
                    self.event_worker,
                    self.notification_worker,
                    self.fanout_worker,
                    self.event_fanout_worker,
                    self.sweep_worker,
                ):
                    await worker.start()
                    started.append(worker)
            except BaseException:
                for resource in reversed(started):
                    await self._stop_one(resource)
                self._state = ContainerState.NEW
                raise
            self._state = ContainerState.STARTED

    async def stop(self) -> None:
        async with self._lock:
            if self._state is ContainerState.STOPPED:
                return
            self._state = ContainerState.STOPPING
            for resource in (
                self.sweep_worker,
                self.notification_worker,
                self.fanout_worker,
                self.event_fanout_worker,
                self.event_worker,
                self.rabbit,
                self.supabase,
            ):
                await self._stop_one(resource)
            self._state = ContainerState.STOPPED

    async def _stop_one(self, resource: object) -> None:
        operation = getattr(resource, "stop", None) or getattr(resource, "close", None)
        if operation is None:
            return
        try:
            await operation()
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.warning("No se pudo cerrar un recurso de la aplicación")


def build_container(settings: Settings, resources: AppResources) -> RuntimeContainer:
    """Ensambla el RuntimeContainer resolviendo el grafo del Dependencies container.

    Es el único grafo de la aplicación: lo usan las rutas HTTP, los WebSockets y los
    workers, así que comparten una sola conexión a Supabase y una sola a RabbitMQ."""
    container = Dependencies()
    container.settings.override(providers.Object(settings))
    container.websocket_manager.override(providers.Object(resources.websocket_manager))
    container.rate_limiter.override(providers.Object(resources.rate_limiter))

    supabase = container.supabase()
    rabbit = container.rabbit()
    topology = container.topology()
    ids = container.ids()
    events = container.events()
    jobs = container.jobs()
    live_delivery = container.live_delivery()

    channels, seen = _select_channels(settings, live_delivery)

    notification_repository = container.notification_repository()
    notification_persistence = container.notification_persistence()

    auth = container.auth()
    empresas = container.empresas()
    notifications = NotificationUseCases(
        notification_repository,
        notification_persistence,
        jobs,
        DeliveryDispatcher(tuple(channels)),
        live_delivery if "websocket" in seen else None,
        ids,
    )
    turns = TurnUseCases(
        container.turns_repository(),
        container.queues_repository(),
        events,
        notifications,
        container.clock(),
        enforce_ownership=settings.ENFORCE_TURN_OWNERSHIP,
    )
    sweeps = SweepUseCases(
        container.sweep_repository(),
        events,
        notifications,
        container.clock(),
        settings.NO_SHOW_GRACIA_MINUTOS,
        settings.RECORDATORIO_ANTICIPACION_MINUTOS,
    )

    # Eventos de cola: la cola dedicada la consume UNA instancia y el evento se difunde a
    # TODAS (exchange fanout), que entregan a sus propios WebSockets.
    event_worker = EventWorker(
        container.subscription_source(),
        QueueEventDistributor(container.events_fanout(), resources.websocket_manager),
        rabbit,
        topology,
        container.queue_event_parser(),
    )
    event_fanout_worker = FanoutWorker(
        rabbit,
        topology.ensure_events_fanout_queue,
        container.fanout_event_parser(),
        lambda event: resources.websocket_manager.send(event.queue_id, event),
        name="worker-difusion-eventos",
    )
    queues_repository = container.queues_repository()
    queues = QueueUseCases(
        queues_repository,
        queues_repository,
        SubscribingQueueProvisioner(topology, event_worker),
        container.clock(),
    )

    notification_worker = NotificationWorker(
        rabbit,
        topology,
        notifications,
        container.notification_job_parser(),
        settings.NOTIFICACIONES_MAX_INTENTOS,
        settings.NOTIFICACIONES_REINTENTO_SEGUNDOS,
    )
    fanout_worker = FanoutWorker(
        rabbit,
        topology.ensure_fanout_queue,
        container.fanout_notification_parser(),
        lambda notification: resources.websocket_manager.send(
            notification.identity, notification.message
        ),
        name="worker-difusion-notificaciones",
    )
    sweep_worker = ScheduledSweepWorker(
        sweeps,
        settings.TAREAS_INTERVALO_SEGUNDOS,
        enabled=bool(settings.SUPABASE_URL and settings.SUPABASE_KEY),
    )
    return RuntimeContainer(
        settings=settings,
        supabase=supabase,
        rabbit=rabbit,
        auth=auth,
        empresas=empresas,
        queues=queues,
        turns=turns,
        notifications=notifications,
        sweeps=sweeps,
        event_worker=event_worker,
        notification_worker=notification_worker,
        fanout_worker=fanout_worker,
        event_fanout_worker=event_fanout_worker,
        sweep_worker=sweep_worker,
        resources=resources,
    )
