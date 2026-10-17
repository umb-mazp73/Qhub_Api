import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.entities import Turno
from app.domain.enums import PropietarioTipo, TurnoEstado


class TurnoCrear(BaseModel):
    """`franja_inicio` decide el tipo de turno:

    * omitido → turno EN VIVO: se asigna la franja que contiene a "ahora". Si la cola
      está cerrada en este momento, responde 400 con el horario de atención.
    * presente → turno PROGRAMADO: se normaliza al comienzo de la franja que lo
      contiene, así mandar 15:07 cae en la franja de las 15:00.

    Si la franja pedida está llena se responde 409 y NO se reasigna nada: el cliente
    elige otra franja u otro día (ver GET /colas/{id}/franjas para ver disponibilidad).
    """

    cola_id: uuid.UUID
    franja_inicio: datetime | None = None


class TurnoOut(BaseModel):
    id: uuid.UUID
    cola_id: uuid.UUID
    propietario_tipo: PropietarioTipo
    propietario_id: uuid.UUID
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
    recordatorio_enviado_en: datetime | None = None

    @classmethod
    def from_domain(cls, turn: Turno) -> "TurnoOut":
        return cls(
            id=turn.id,
            cola_id=turn.cola_id,
            propietario_tipo=turn.owner.tipo,
            propietario_id=turn.owner.id,
            propietario_nombre=turn.propietario_nombre,
            usuario_id=turn.usuario_id,
            franja_inicio=turn.franja_inicio,
            franja_fecha=turn.franja_fecha,
            programado=turn.programado,
            numero=turn.numero,
            estado=turn.estado,
            posicion=turn.posicion,
            hora_creacion=turn.hora_creacion,
            hora_atencion=turn.hora_atencion,
            hora_finalizacion=turn.hora_finalizacion,
            agente_id=turn.agente_id,
            recordatorio_enviado_en=turn.recordatorio_enviado_en,
        )
