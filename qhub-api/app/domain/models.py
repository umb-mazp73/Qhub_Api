from dataclasses import dataclass
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Mapping, TypeAlias, TypeVar
from uuid import UUID

from app.domain.entities import Cola, Empresa, Notificacion, Turno
from app.domain.enums import PropietarioTipo, TurnoEstado
from app.domain.value_objects import OwnerId, PersonIdentity


class UnsetType:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = UnsetType()
T = TypeVar("T")
Change: TypeAlias = T | UnsetType


@dataclass(frozen=True, slots=True)
class RegisterAccount:
    tipo_cuenta: PropietarioTipo
    nombre_empresa: str | None
    nombre: str
    apellido: str
    nombre_usuario: str
    email: str
    password: str
    pais: str
    ciudad: str
    acepto_terminos: bool


@dataclass(frozen=True, slots=True)
class RegistrationDraft:
    tipo_cuenta: PropietarioTipo
    owner: OwnerId | None
    nombre_empresa: str | None
    nombre: str
    apellido: str
    nombre_usuario: str
    email: str
    password_hash: str
    pais: str
    ciudad: str
    acepto_terminos_en: datetime


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    owner: OwnerId
    nombre_usuario: str
    email: str
    nombre_empresa: str | None
    limite_colas: int
    creada_en: datetime


@dataclass(frozen=True, slots=True)
class LoginCommand:
    identificador: str | None
    password: str | None
    api_key: str | None


@dataclass(frozen=True, slots=True)
class RequestPasswordReset:
    email: str


@dataclass(frozen=True, slots=True)
class ChangePassword:
    identificador: str
    current_password: str
    new_password: str


@dataclass(frozen=True, slots=True)
class ResetPassword:
    token: str
    new_password: str


@dataclass(frozen=True, slots=True)
class CreateEmpresa:
    nombre: str


@dataclass(frozen=True, slots=True)
class EmpresaChanges:
    nombre: Change[str] = UNSET
    activa: Change[bool] = UNSET


@dataclass(frozen=True, slots=True)
class EmpresaWithApiKey:
    empresa: Empresa
    api_key: str


@dataclass(frozen=True, slots=True)
class CreateQueue:
    nombre: str
    descripcion: str | None
    hora_apertura: time | None
    hora_cierre: time | None
    duracion_franja_minutos: int | None
    dias_atencion: tuple[int, ...] | None
    duracion_turno_minutos: int | None
    puestos: int | None
    capacidad_diaria: int | None
    dias_anticipacion_maxima: int | None


@dataclass(frozen=True, slots=True)
class QueueChanges:
    nombre: Change[str] = UNSET
    descripcion: Change[str | None] = UNSET
    activa: Change[bool] = UNSET


@dataclass(frozen=True, slots=True)
class QueueSchedule:
    hora_apertura: time
    hora_cierre: time
    duracion_franja_minutos: int
    dias_atencion: tuple[int, ...]
    duracion_turno_minutos: int
    puestos: int
    capacidad_diaria: int
    dias_anticipacion_maxima: int
    zona_horaria: str | None


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    cola: Cola
    franjas_por_dia: int
    cupos_por_franja: int
    turnos_por_dia: int


DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 1000  # tope de filas por consulta de Supabase (PostgREST)


@dataclass(frozen=True, slots=True)
class Page:
    """Ventana de un listado. Sin ella, un historial largo se cortaría en silencio en el
    tope de Supabase y sin un orden que permita continuar."""

    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TurnQuery:
    cola_id: UUID | None
    estado: TurnoEstado | None
    fecha: date | None
    page: Page = Page()


@dataclass(frozen=True, slots=True)
class CreateTurn:
    cola_id: UUID
    franja_inicio: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    mensaje: str
    turno_id: UUID | None
    clave_idempotencia: UUID


@dataclass(frozen=True, slots=True)
class PersistNotification:
    identity: PersonIdentity
    message: str
    turn_id: UUID | None
    idempotency_key: UUID | None


@dataclass(frozen=True, slots=True)
class NotificationJob:
    key: UUID
    identity: PersonIdentity
    message: str
    turn_id: UUID | None
    notice_type: str = "generica"


@dataclass(frozen=True, slots=True)
class RequestNotification:
    identity: PersonIdentity
    message: str
    turn_id: UUID | None
    notice_type: str


@dataclass(frozen=True, slots=True)
class NotificationRequestResult:
    queued: bool
    persisted: bool


@dataclass(frozen=True, slots=True)
class PersonalNotificationWire:
    notification_id: str
    message: str
    turn_id: str | None
    notice_type: str
    read: bool
    created_at: str

    @classmethod
    def from_notification(
        cls, notification: Notificacion, notice_type: str
    ) -> "PersonalNotificationWire":
        if notification.creada_en.tzinfo is None:
            raise ValueError("creada_en debe incluir zona horaria")
        return cls(
            notification_id=str(notification.id),
            message=notification.mensaje,
            turn_id=str(notification.turno_id) if notification.turno_id else None,
            notice_type=notice_type,
            read=notification.leida,
            created_at=notification.creada_en.isoformat(),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "tipo": "notificacion",
            "notificacion": {
                "id": self.notification_id,
                "mensaje": self.message,
                "turno_id": self.turn_id,
                "tipo_aviso": self.notice_type,
                "leida": self.read,
                "creada_en": self.created_at,
            },
        }


@dataclass(frozen=True, slots=True)
class FanoutNotification:
    identity: PersonIdentity
    message: PersonalNotificationWire


@dataclass(frozen=True, slots=True)
class QueueEvent:
    event_type: str
    queue_id: UUID
    payload: Turno


FrozenJsonScalar: TypeAlias = str | int | float | bool | None
FrozenJson: TypeAlias = (
    FrozenJsonScalar | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)


def freeze_json(value: object) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("value is not a JSON tree")


def thaw_json(value: FrozenJson) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class QueueEventEnvelope:
    queue_id: UUID
    event_type: str
    payload: Mapping[str, FrozenJson]
    raw_wire: Mapping[str, FrozenJson]

    def to_wire(self) -> dict[str, object]:
        wire = thaw_json(self.raw_wire)
        if not isinstance(wire, dict):
            raise TypeError("raw_wire must thaw to a mapping")
        return wire


@dataclass(frozen=True, slots=True)
class SweepResult:
    no_show: int
    recordatorios: int
