from app.domain.enums import TurnoEstado
from app.domain.errors import InvalidTurnTransition


_TRANSITION_ERRORS: dict[str, tuple[frozenset[TurnoEstado], str]] = {
    "posponer": (
        frozenset({TurnoEstado.EN_ESPERA}),
        "Solo se puede posponer un turno en espera",
    ),
    "cancelar": (
        frozenset({TurnoEstado.EN_ESPERA, TurnoEstado.ATENDIENDO}),
        "El turno ya no se puede cancelar",
    ),
    "atender": (
        frozenset({TurnoEstado.EN_ESPERA}),
        "Solo se puede atender un turno en espera",
    ),
    "finalizar": (
        frozenset({TurnoEstado.ATENDIENDO}),
        "Solo se puede finalizar un turno que se está atendiendo",
    ),
    "no_show": (
        frozenset({TurnoEstado.EN_ESPERA, TurnoEstado.ATENDIENDO}),
        "El turno ya no se puede marcar como no-show",
    ),
}


def validar_transicion(estado: TurnoEstado, accion: str) -> None:
    try:
        permitidos, detail = _TRANSITION_ERRORS[accion]
    except KeyError as exc:
        raise ValueError(f"Acción de turno desconocida: {accion}") from exc
    if estado not in permitidos:
        raise InvalidTurnTransition(detail)

