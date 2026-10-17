from enum import Enum


class PropietarioTipo(str, Enum):
    """Los dos tipos de cuenta que pueden ser dueños de colas (enum propietario_tipo
    en schema.sql). Una Empresa es una entidad con personas que la administran
    (`control_empresas`); un Usuario es una persona individual que es dueña ella misma."""

    EMPRESA = "empresa"
    USUARIO = "usuario"


class TurnoEstado(str, Enum):
    EN_ESPERA = "en_espera"
    ATENDIENDO = "atendiendo"
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"
    NO_SHOW = "no_show"


class DiaSemana(int, Enum):
    LUNES = 1
    MARTES = 2
    MIERCOLES = 3
    JUEVES = 4
    VIERNES = 5
    SABADO = 6
    DOMINGO = 7


LIMITE_COLAS_POR_TIPO: dict[PropietarioTipo, int] = {
    PropietarioTipo.EMPRESA: 6,
    PropietarioTipo.USUARIO: 3,
}

ESTADOS_QUE_LIBERAN_CUPO: frozenset[str] = frozenset(
    {TurnoEstado.CANCELADO.value, TurnoEstado.NO_SHOW.value}
)
