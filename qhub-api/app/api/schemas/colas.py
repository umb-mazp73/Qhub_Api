import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.entities import Cola
from app.domain.enums import PropietarioTipo
from app.domain.queue_rules import HORARIO_DEFAULT
from app.domain.value_objects import Franja, QueueLimit, QueueState
from app.domain.models import ScheduleResult


class ColaCrear(BaseModel):
    """El horario es opcional al crear: si no se manda, la cola arranca con los
    defaults del schema (09:00–18:00, franjas de 30 min, lunes a sábado, sin tope
    diario) y se ajusta después con PUT /colas/{id}/horario."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    hora_apertura: time | None = None
    hora_cierre: time | None = None
    duracion_franja_minutos: int | None = Field(default=None, ge=5, le=480)
    dias_atencion: list[int] | None = None
    duracion_turno_minutos: int | None = Field(default=None, ge=1, le=480)
    puestos: int | None = Field(default=None, ge=1, le=100)
    capacidad_diaria: int | None = Field(default=None, ge=0)
    dias_anticipacion_maxima: int | None = Field(default=None, ge=0, le=365)

    @field_validator("dias_atencion")
    @classmethod
    def _dias_validos(cls, valor: list[int] | None) -> list[int] | None:
        if valor is None:
            return None
        if not valor:
            raise ValueError("dias_atencion no puede estar vacío")
        fuera = sorted(set(d for d in valor if d < 1 or d > 7))
        if fuera:
            raise ValueError(
                f"dias_atencion usa formato ISO (1=lunes … 7=domingo); valores inválidos: {fuera}"
            )
        return sorted(set(valor))

    @model_validator(mode="after")
    def _horario_coherente(self) -> "ColaCrear":
        if (
            self.hora_apertura is not None
            and self.hora_cierre is not None
            and self.hora_cierre <= self.hora_apertura
        ):
            raise ValueError("hora_cierre tiene que ser posterior a hora_apertura")
        slot = self.duracion_franja_minutos or HORARIO_DEFAULT["duracion_franja_minutos"]
        turn = self.duracion_turno_minutos or HORARIO_DEFAULT["duracion_turno_minutos"]
        if turn > slot:
            raise ValueError(f"Un turno de {turn} minutos no cabe en una franja de {slot} minutos")
        return self


class ColaActualizar(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    descripcion: str | None = None
    activa: bool | None = None


class HorarioActualizar(BaseModel):
    """PUT /colas/{id}/horario — define el horario de atención y las franjas.

    Los cupos de cada franja NO se configuran a mano: salen de
    `floor(duracion_franja / duracion_turno) * puestos`. Con franjas de 30 min y un
    puesto, un trámite de 3 min da 10 cupos; uno de 15 min da 2.

    `capacidad_diaria` es un tope OPCIONAL del día (0 = sin tope), para el negocio que
    además quiera un techo por debajo de lo que darían las franjas."""

    model_config = ConfigDict(extra="forbid")

    hora_apertura: time
    hora_cierre: time
    duracion_franja_minutos: int = Field(ge=5, le=480)
    dias_atencion: list[int]
    duracion_turno_minutos: int = Field(ge=1, le=480)
    puestos: int = Field(default=1, ge=1, le=100)
    capacidad_diaria: int = Field(default=0, ge=0)
    dias_anticipacion_maxima: int = Field(ge=0, le=365)
    zona_horaria: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("dias_atencion")
    @classmethod
    def _dias_validos(cls, valor: list[int]) -> list[int]:
        if not valor:
            raise ValueError("dias_atencion no puede estar vacío")
        fuera = sorted(set(d for d in valor if d < 1 or d > 7))
        if fuera:
            raise ValueError(
                f"dias_atencion usa formato ISO (1=lunes … 7=domingo); valores inválidos: {fuera}"
            )
        return sorted(set(valor))


class ColaOut(BaseModel):
    id: uuid.UUID
    propietario_tipo: PropietarioTipo
    propietario_id: uuid.UUID
    propietario_nombre: str
    nombre: str
    descripcion: str | None
    activa: bool
    rabbitmq_queue_name: str

    @classmethod
    def from_domain(cls, queue: Cola) -> "ColaOut":
        return cls(
            id=queue.id,
            propietario_tipo=queue.owner.tipo,
            propietario_id=queue.owner.id,
            propietario_nombre=queue.propietario_nombre,
            nombre=queue.nombre,
            descripcion=queue.descripcion,
            activa=queue.activa,
            rabbitmq_queue_name=queue.rabbitmq_queue_name,
        )


class HorarioOut(BaseModel):
    """El horario configurado más lo que se deriva de él, para que el cliente no tenga
    que recalcular las franjas ni los cupos por su cuenta."""

    cola_id: uuid.UUID
    zona_horaria: str
    hora_apertura: time
    hora_cierre: time
    duracion_franja_minutos: int
    dias_atencion: list[int]
    duracion_turno_minutos: int
    puestos: int
    capacidad_diaria: int
    dias_anticipacion_maxima: int
    franjas_por_dia: int
    cupos_por_franja: int
    turnos_por_dia: int

    @classmethod
    def from_result(cls, result: ScheduleResult) -> "HorarioOut":
        queue = result.cola
        return cls(
            cola_id=queue.id,
            zona_horaria=queue.zona_horaria,
            hora_apertura=queue.hora_apertura,
            hora_cierre=queue.hora_cierre,
            duracion_franja_minutos=queue.duracion_franja_minutos,
            dias_atencion=list(queue.dias_atencion),
            duracion_turno_minutos=queue.duracion_turno_minutos,
            puestos=queue.puestos,
            capacidad_diaria=queue.capacidad_diaria,
            dias_anticipacion_maxima=queue.dias_anticipacion_maxima,
            franjas_por_dia=result.franjas_por_dia,
            cupos_por_franja=result.cupos_por_franja,
            turnos_por_dia=result.turnos_por_dia,
        )


class FranjaOut(BaseModel):
    inicio: datetime
    fin: datetime
    cupos: int
    ocupados: int
    disponibles: int

    @classmethod
    def from_domain(cls, slot: Franja) -> "FranjaOut":
        return cls(**{name: getattr(slot, name) for name in cls.model_fields})


class ColaEstado(BaseModel):
    cola_id: uuid.UUID
    turnos_en_espera: int
    turnos_atendiendo: int

    @classmethod
    def from_domain(cls, state: QueueState) -> "ColaEstado":
        return cls(**{name: getattr(state, name) for name in cls.model_fields})


class ColasLimite(BaseModel):
    propietario_tipo: PropietarioTipo
    limite: int
    activas: int
    disponibles: int

    @classmethod
    def from_domain(cls, limit: QueueLimit) -> "ColasLimite":
        return cls(**{name: getattr(limit, name) for name in cls.model_fields})
