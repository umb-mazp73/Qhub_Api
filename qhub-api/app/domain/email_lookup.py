"""Lógica pura (solo stdlib + dominio) de a qué tabla/columnas consultar el correo de
un destinatario, según el tipo de dueño. Sin dependencias de Supabase: importable y
testeable con el runner solo-stdlib.

Devuelve `(tabla, filtros_de_igualdad)` o `None` cuando no hay forma segura de resolver
un correo (p. ej. `usuario_id` que no es un UUID para un dueño empresa). `None` hace que
el canal omita el envío con gracia, nunca adivina ni envía a la dirección equivocada."""

from uuid import UUID

from app.domain.enums import PropietarioTipo
from app.domain.value_objects import PersonIdentity


def email_query_for(identity: PersonIdentity) -> tuple[str, dict[str, str]] | None:
    """Tabla + filtros de igualdad para buscar el `email` del destinatario, o `None`.

    - Dueño USUARIO: el dueño ES la persona. `usuarios` por `id == owner.id`.
    - Dueño EMPRESA: el único correo almacenado es el de la cuenta `control_empresas`;
      el `usuario_id` del turno identifica esa cuenta. Si es un UUID válido, filtrar
      `control_empresas` por `empresa_id == owner.id` y `id == usuario_id`; si no es un
      UUID, devolver `None` (nunca consultamos por un id inválido).
    """
    owner = identity.owner
    if owner.tipo is PropietarioTipo.USUARIO:
        return "usuarios", {"id": str(owner.id)}
    if owner.tipo is PropietarioTipo.EMPRESA:
        try:
            UUID(identity.usuario_id)
        except (ValueError, AttributeError, TypeError):
            return None
        return "control_empresas", {"empresa_id": str(owner.id), "id": identity.usuario_id}
    return None
