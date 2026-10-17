from datetime import date, datetime, time
from uuid import UUID

from app.domain.entities import Cola, Empresa, Notificacion, Turno
from app.domain.enums import PropietarioTipo, TurnoEstado
from app.domain.value_objects import Franja, OwnerId, PersonIdentity


def _datetime(value: datetime | str) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _time(value: time | str) -> time:
    return value if isinstance(value, time) else time.fromisoformat(value)


def owner_from_row(row: dict[str, object]) -> OwnerId:
    return OwnerId(PropietarioTipo(str(row["propietario_tipo"])), UUID(str(row["propietario_id"])))


def empresa_from_row(row: dict[str, object]) -> Empresa:
    return Empresa(
        id=UUID(str(row["id"])),
        nombre=str(row["nombre"]),
        activa=bool(row["activa"]),
        creada_en=_datetime(row["creada_en"]),
    )


def cola_from_row(row: dict[str, object]) -> Cola:
    return Cola(
        id=UUID(str(row["id"])),
        owner=owner_from_row(row),
        propietario_nombre=str(row["propietario_nombre"]),
        nombre=str(row["nombre"]),
        descripcion=None if row.get("descripcion") is None else str(row["descripcion"]),
        activa=bool(row["activa"]),
        zona_horaria=str(row["zona_horaria"]),
        hora_apertura=_time(row["hora_apertura"]),
        hora_cierre=_time(row["hora_cierre"]),
        duracion_franja_minutos=int(row["duracion_franja_minutos"]),
        dias_atencion=tuple(int(day) for day in row["dias_atencion"]),
        duracion_turno_minutos=int(row["duracion_turno_minutos"]),
        puestos=int(row["puestos"]),
        capacidad_diaria=int(row["capacidad_diaria"]),
        dias_anticipacion_maxima=int(row["dias_anticipacion_maxima"]),
        rabbitmq_queue_name=str(row["rabbitmq_queue_name"]),
    )


def turno_from_row(row: dict[str, object]) -> Turno:
    def optional_datetime(name: str) -> datetime | None:
        value = row.get(name)
        return None if value is None else _datetime(value)

    return Turno(
        id=UUID(str(row["id"])),
        cola_id=UUID(str(row["cola_id"])),
        owner=owner_from_row(row),
        propietario_nombre=str(row["propietario_nombre"]),
        usuario_id=str(row["usuario_id"]),
        franja_inicio=_datetime(row["franja_inicio"]),
        franja_fecha=_date(row["franja_fecha"]),
        programado=bool(row["programado"]),
        numero=int(row["numero"]),
        estado=TurnoEstado(str(row["estado"])),
        posicion=int(row["posicion"]),
        hora_creacion=_datetime(row["hora_creacion"]),
        hora_atencion=optional_datetime("hora_atencion"),
        hora_finalizacion=optional_datetime("hora_finalizacion"),
        agente_id=None if row.get("agente_id") is None else str(row["agente_id"]),
        recordatorio_enviado_en=optional_datetime("recordatorio_enviado_en"),
    )


def notificacion_from_row(row: dict[str, object]) -> Notificacion:
    identity = PersonIdentity(owner_from_row(row), str(row["usuario_id"]))
    turn_id = row.get("turno_id")
    idempotency_key = row.get("clave_idempotencia")
    return Notificacion(
        id=UUID(str(row["id"])),
        identity=identity,
        turno_id=None if turn_id is None else UUID(str(turn_id)),
        mensaje=str(row["mensaje"]),
        leida=bool(row["leida"]),
        creada_en=_datetime(row["creada_en"]),
        clave_idempotencia=(
            None if idempotency_key is None else UUID(str(idempotency_key))
        ),
    )


def franja_from_row(row: dict[str, object]) -> Franja:
    return Franja(
        inicio=_datetime(row["inicio"]),
        fin=_datetime(row["fin"]),
        cupos=int(row["cupos"]),
        ocupados=int(row["ocupados"]),
        disponibles=int(row["disponibles"]),
    )
