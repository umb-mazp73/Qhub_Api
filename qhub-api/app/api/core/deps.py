from uuid import UUID

from fastapi import Depends, HTTPException, Request

from app.api.core.error_handlers import STATUS_BY_TYPE
from app.api.core.security import get_current_user, requerir_rol
from app.application.errors import ApplicationError
from app.application.use_cases.auth import AuthUseCases
from app.application.use_cases.colas import QueueUseCases
from app.application.use_cases.empresas import EmpresaUseCases
from app.application.use_cases.notificaciones import NotificationUseCases
from app.application.use_cases.turnos import TurnUseCases
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import OwnerId, PersonIdentity, TenantContext


def http_error(error: ApplicationError) -> HTTPException:
    return HTTPException(STATUS_BY_TYPE.get(type(error), 500), error.detail)


def owner_from_claims(value: dict | None) -> OwnerId | None:
    """Cuenta dueña (propietario_tipo + propietario_id) que viaja firmada en el token."""
    if value is None:
        return None
    return OwnerId(
        PropietarioTipo(value["propietario_tipo"]),
        UUID(str(value["propietario_id"])),
    )


def context_from_claims(value: dict) -> TenantContext:
    owner = owner_from_claims(value)
    assert owner is not None
    return TenantContext(
        PersonIdentity(owner, value["usuario_id"]), value.get("rol") or "cliente"
    )


# Los casos de uso viven en el contenedor de la app (una conexión a Supabase y una a
# RabbitMQ por proceso, compartidas por todas las requests): no se construyen por request.
def get_container(request: Request):
    return request.app.state.container


def get_auth_use_cases(container=Depends(get_container)) -> AuthUseCases:
    return container.auth


def get_empresa_use_cases(container=Depends(get_container)) -> EmpresaUseCases:
    return container.empresas


def get_queue_use_cases(container=Depends(get_container)) -> QueueUseCases:
    return container.queues


def get_turn_use_cases(container=Depends(get_container)) -> TurnUseCases:
    return container.turns


def get_notification_use_cases(
    container=Depends(get_container),
) -> NotificationUseCases:
    return container.notifications


def get_tenant_context(usuario: dict = Depends(get_current_user)) -> TenantContext:
    return context_from_claims(usuario)


def get_admin_context(
    usuario: dict = Depends(requerir_rol("admin")),
) -> TenantContext:
    return context_from_claims(usuario)


def get_agent_context(
    usuario: dict = Depends(requerir_rol("agente")),
) -> TenantContext:
    return context_from_claims(usuario)
