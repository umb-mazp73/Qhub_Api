from functools import lru_cache

from pydantic import field_validator

from app.config.base import EnvConfig


class Settings(EnvConfig):
    APP_NAME: str = "Qhub-api"
    APP_ENV: str = "development"
    DEBUG: bool = True

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ACCESS_TOKEN_EXPIRE_MINUTOS: int = 60
    ADMIN_API_KEY: str = ""

    RABBITMQ_URL: str = ""
    RABBITMQ_EXCHANGE: str = "qhub.eventos"
    RABBITMQ_DLX: str = "qhub.dlx"
    RABBITMQ_DLQ: str = "qhub.dlq"
    RABBITMQ_NOTIFICACIONES_QUEUE: str = "qhub.notificaciones"
    RABBITMQ_NOTIFICACIONES_FANOUT: str = "qhub.notificaciones.difusion"
    RABBITMQ_EVENTOS_FANOUT: str = "qhub.eventos.difusion"

    NOTIFICACIONES_MAX_INTENTOS: int = 5
    NOTIFICACIONES_REINTENTO_SEGUNDOS: int = 5
    NOTIFICACIONES_CANALES: str = "websocket,log"

    TAREAS_INTERVALO_SEGUNDOS: int = 60
    NO_SHOW_GRACIA_MINUTOS: int = 15
    RECORDATORIO_ANTICIPACION_MINUTOS: int = 60

    WS_HEARTBEAT_INTERVAL: int = 30
    RATE_LIMIT_REQUESTS_POR_MINUTO: int = 300
    RATE_LIMIT_AUTH_POR_MINUTO: int = 20
    CORS_ORIGINS: str = "*"

    # Si es true, quien no es admin ni agente solo ve, cancela o pospone SUS turnos (usuario_id de X-Usuario-Id);
    # el ajeno responde 404. Apagado por defecto para no cambiar el comportamiento de los clientes existentes.
    ENFORCE_TURN_OWNERSHIP: bool = False

    @field_validator("NOTIFICACIONES_MAX_INTENTOS")
    @classmethod
    def _max_intentos_positivo(cls, value: int) -> int:
        if value < 1:
            raise ValueError("NOTIFICACIONES_MAX_INTENTOS debe ser mayor o igual a 1")
        return value

    @field_validator("NOTIFICACIONES_REINTENTO_SEGUNDOS")
    @classmethod
    def _reintento_no_negativo(cls, value: int) -> int:
        if value < 0:
            raise ValueError("NOTIFICACIONES_REINTENTO_SEGUNDOS no puede ser negativo")
        return value

    @field_validator("TAREAS_INTERVALO_SEGUNDOS", "WS_HEARTBEAT_INTERVAL")
    @classmethod
    def _intervalo_positivo(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("el intervalo debe ser mayor que cero")
        return value

    @field_validator("NO_SHOW_GRACIA_MINUTOS")
    @classmethod
    def _gracia_no_negativa(cls, value: int) -> int:
        return max(value, 0)

    def production_warnings(self) -> list[str]:
        """Configuración que no conviene en producción. Solo avisa: no impide arrancar."""
        problems = []
        if self.DEBUG:
            problems.append("DEBUG=true: desactivarlo en producción")
        if self.cors_origins_list == ["*"]:
            problems.append("CORS_ORIGINS=*: poner los orígenes reales")
        if len(self.JWT_SECRET_KEY) < 32:
            problems.append("JWT_SECRET_KEY vacía o corta (mínimo 32 caracteres)")
        if len(self.ADMIN_API_KEY) < 32:
            problems.append("ADMIN_API_KEY vacía o corta (mínimo 32 caracteres)")
        if not (self.SUPABASE_URL and self.SUPABASE_KEY):
            problems.append("SUPABASE_URL / SUPABASE_KEY sin configurar")
        if not self.RABBITMQ_URL:
            problems.append("RABBITMQ_URL sin configurar: sin broker no hay eventos entre instancias ni reintentos de avisos")
        return problems

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
