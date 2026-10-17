from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.application.errors import ApplicationError
from app.domain.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.application.use_cases.notificaciones import NotificationUseCases
from app.api.core.deps import (
    get_notification_use_cases,
    get_tenant_context,
    http_error,
)
from app.api.schemas.notificaciones import NotificacionOut

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("", response_model=list[NotificacionOut])
async def listar_notificaciones(
    limite: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Máximo de avisos a devolver"),
    desde: int = Query(0, ge=0, description="Cuántos avisos saltar (para paginar)"),
    context=Depends(get_tenant_context),
    casos: NotificationUseCases = Depends(get_notification_use_cases),
):
    """Los avisos de la persona que hace la petición (X-Usuario-Id), del más nuevo al más viejo."""
    return [
        NotificacionOut.from_domain(item)
        for item in await casos.list(context, Page(limite, desde))
    ]


@router.patch("/{notificacion_id}/leida", response_model=NotificacionOut)
async def marcar_leida(
    notificacion_id: UUID,
    context=Depends(get_tenant_context),
    casos: NotificationUseCases = Depends(get_notification_use_cases),
):
    try:
        return NotificacionOut.from_domain(
            await casos.mark_read(context, notificacion_id)
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.delete("/{notificacion_id}", status_code=204)
async def eliminar_notificacion(
    notificacion_id: UUID,
    context=Depends(get_tenant_context),
    casos: NotificationUseCases = Depends(get_notification_use_cases),
):
    try:
        await casos.delete(context, notificacion_id)
    except ApplicationError as exc:
        raise http_error(exc) from exc
