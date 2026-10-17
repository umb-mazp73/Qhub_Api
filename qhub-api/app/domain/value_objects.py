from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import PropietarioTipo


@dataclass(frozen=True, slots=True)
class OwnerId:
    tipo: PropietarioTipo
    id: UUID


@dataclass(frozen=True, slots=True)
class PersonIdentity:
    owner: OwnerId
    usuario_id: str

    def __post_init__(self) -> None:
        if not self.usuario_id:
            raise ValueError("usuario_id no puede estar vacío")


@dataclass(frozen=True, slots=True)
class TenantContext:
    identity: PersonIdentity
    rol: str = "cliente"


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class LoginRecord:
    owner: OwnerId
    password_hash: str
    account_active: bool
    owner_active: bool


@dataclass(frozen=True, slots=True)
class Franja:
    inicio: datetime
    fin: datetime
    cupos: int
    ocupados: int
    disponibles: int


@dataclass(frozen=True, slots=True)
class QueueState:
    cola_id: UUID
    turnos_en_espera: int
    turnos_atendiendo: int


@dataclass(frozen=True, slots=True)
class QueueLimit:
    propietario_tipo: PropietarioTipo
    limite: int
    activas: int
    disponibles: int


@dataclass(frozen=True, slots=True)
class QueueSubscription:
    queue_id: UUID
    broker_queue_name: str
