from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.entities import Notificacion
from app.domain.enums import PropietarioTipo


class NotificacionOut(BaseModel):
    id: UUID
    propietario_tipo: PropietarioTipo
    propietario_id: UUID
    usuario_id: str
    turno_id: UUID | None
    mensaje: str
    leida: bool
    creada_en: datetime

    @classmethod
    def from_domain(cls, value: Notificacion) -> "NotificacionOut":
        return cls(
            id=value.id,
            propietario_tipo=value.identity.owner.tipo,
            propietario_id=value.identity.owner.id,
            usuario_id=value.identity.usuario_id,
            turno_id=value.turno_id,
            mensaje=value.mensaje,
            leida=value.leida,
            creada_en=value.creada_en,
        )
