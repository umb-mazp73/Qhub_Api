from app.application.errors import (
    ApplicationError,
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    PersistenceFailure,
    UnprocessableInput,
)
from app.domain.enums import LIMITE_COLAS_POR_TIPO, PropietarioTipo


def _value(error: object, name: str) -> str | None:
    value = getattr(error, name, None)
    if value is None and isinstance(error, dict):
        value = error.get(name)
    return None if value is None else str(value)


def provider_code(error: object) -> str | None:
    return _value(error, "code")


def provider_message(error: object) -> str:
    return _value(error, "message") or ""


def map_turn_rpc_error(error: object) -> ApplicationError:
    code = provider_code(error)
    message = provider_message(error)
    if code == "QNFD1":
        return NotFound("Cola no encontrada", "cola")
    if code == "QINA1":
        return BadRequest("La cola no está activa", code)
    schedule_defaults = {
        "QFRA1": "Fuera del horario de atención de la cola",
        "QFRA2": "Esa franja ya pasó",
        "QFRA3": "La fecha está más allá de lo que permite reservar esta cola",
    }
    if code in schedule_defaults:
        return BadRequest(message or schedule_defaults[code], code)
    capacity_defaults = {
        "QCAP1": "Esa franja está ocupada. Elegí otra franja u otro día.",
        "QCAP2": "El cupo del día está agotado. Elegí otro día.",
    }
    if code in capacity_defaults:
        return Conflict(message or capacity_defaults[code], code)
    return Conflict("No se pudo crear el turno, intentá de nuevo", code)


def map_registration_error(error: object) -> ApplicationError:
    code = provider_code(error)
    if code == "23505":
        # El pre-chequeo del caso de uso no ve una carrera entre dos registros simultáneos:
        # la base (índices únicos entre email y nombre de usuario) tiene la última palabra.
        return Conflict("El email o el nombre de usuario ya están registrados", code)
    if code == "23514":
        return UnprocessableInput("Los datos de registro no son válidos", code)
    if code == "QEMP1":
        return NotFound("La empresa no existe", "empresa")
    return PersistenceFailure(operation="register")


def map_queue_error(
    error: object,
    operation: str,
    *,
    owner_type: PropietarioTipo | None = None,
) -> ApplicationError:
    code = provider_code(error)
    combined = " ".join(
        filter(None, (_value(error, "message"), _value(error, "details"), _value(error, "hint")))
    )
    if code == "QPRO1":
        return NotFound("La cuenta propietaria no existe", "cuenta_propietaria")
    if code == "QPRO2":
        return Forbidden("La cuenta propietaria no está activa")
    if code == "23514":
        return UnprocessableInput("La configuración de horario no es válida", code)
    if code == "QLIM1":
        if owner_type is not None:
            limit = LIMITE_COLAS_POR_TIPO[owner_type]
            return Conflict(
                f"Alcanzaste el límite de {limit} colas activas de tu cuenta. "
                "Desactivá una cola existente (DELETE /colas/{id}) para liberar un lugar.",
                code,
            )
        return Conflict("Alcanzaste el límite de colas de tu cuenta", code)
    if code == "23505":
        # La unicidad vale solo entre colas ACTIVAS: el nombre de una eliminada está libre.
        if "uq_colas_rabbitmq_queue_name_activas" in combined:
            return Conflict(
                "Ese nombre de cola ya está en uso por otra cola activa, de tu cuenta o de "
                "otra con un nombre muy parecido al tuyo. Probá con un nombre distinto.",
                code,
            )
        return Conflict(
            "Ya tenés una cola activa con ese nombre. Elegí otro, o eliminá la que lo usa "
            "(DELETE /colas/{id}) para liberarlo.",
            code,
        )
    details = {
        "create_queue": "No se pudo crear la cola",
        "update_queue": "No se pudo actualizar la cola",
        "update_schedule": "No se pudo actualizar el horario",
    }
    if operation in details:
        return BadRequest(details[operation], code)
    return PersistenceFailure(operation=operation)
