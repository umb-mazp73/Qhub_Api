from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from app.domain.enums import TurnoEstado
from app.domain.value_objects import OwnerId, PersonIdentity


@dataclass(frozen=True, slots=True)
class Empresa:
    id: UUID
    nombre: str
    activa: bool
    creada_en: datetime


@dataclass(frozen=True, slots=True)
class Cola:
    id: UUID
    owner: OwnerId
    propietario_nombre: str
    nombre: str
    descripcion: str | None
    activa: bool
    zona_horaria: str
    hora_apertura: time
    hora_cierre: time
    duracion_franja_minutos: int
    dias_atencion: tuple[int, ...]
    duracion_turno_minutos: int
    puestos: int
    capacidad_diaria: int
    dias_anticipacion_maxima: int
    rabbitmq_queue_name: str


@dataclass(frozen=True, slots=True)
class Turno:
    id: UUID
    cola_id: UUID
    owner: OwnerId
    propietario_nombre: str
    usuario_id: str
    franja_inicio: datetime
    franja_fecha: date
    programado: bool
    numero: int
    estado: TurnoEstado
    posicion: int
    hora_creacion: datetime
    hora_atencion: datetime | None
    hora_finalizacion: datetime | None
    agente_id: str | None
    recordatorio_enviado_en: datetime | None


@dataclass(frozen=True, slots=True)
class Notificacion:
    id: UUID
    identity: PersonIdentity
    turno_id: UUID | None
    mensaje: str
    leida: bool
    creada_en: datetime
    clave_idempotencia: UUID | None
