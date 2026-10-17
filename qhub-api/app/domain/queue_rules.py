from datetime import time

from app.domain.errors import InvalidSchedule


HORARIO_DEFAULT: dict[str, object] = {
    "hora_apertura": time(9, 0),
    "hora_cierre": time(18, 0),
    "duracion_franja_minutos": 30,
    "dias_atencion": [1, 2, 3, 4, 5, 6],
    "duracion_turno_minutos": 3,
    "puestos": 1,
    "capacidad_diaria": 0,
    "dias_anticipacion_maxima": 7,
}


def franjas_por_dia(hora_apertura: time, hora_cierre: time, duracion_minutos: int) -> int:
    if duracion_minutos <= 0:
        return 0
    minutos_apertura = hora_apertura.hour * 60 + hora_apertura.minute
    minutos_cierre = hora_cierre.hour * 60 + hora_cierre.minute
    if minutos_cierre <= minutos_apertura:
        return 0
    return (minutos_cierre - minutos_apertura) // duracion_minutos


def cupos_por_franja(
    duracion_franja_minutos: int, duracion_turno_minutos: int, puestos: int = 1
) -> int:
    if duracion_franja_minutos <= 0 or duracion_turno_minutos <= 0:
        return 0
    return (duracion_franja_minutos // duracion_turno_minutos) * max(puestos, 1)


def validar_horario(
    hora_apertura: time,
    hora_cierre: time,
    duracion_franja_minutos: int,
    duracion_turno_minutos: int,
) -> None:
    if hora_cierre <= hora_apertura:
        raise InvalidSchedule("hora_cierre tiene que ser posterior a hora_apertura")
    if franjas_por_dia(hora_apertura, hora_cierre, duracion_franja_minutos) == 0:
        raise InvalidSchedule(
            f"El horario {hora_apertura}–{hora_cierre} no alcanza para una franja "
            f"de {duracion_franja_minutos} minutos"
        )
    if duracion_turno_minutos > duracion_franja_minutos:
        raise InvalidSchedule(
            f"Un turno de {duracion_turno_minutos} minutos no cabe en una franja de "
            f"{duracion_franja_minutos} minutos"
        )
