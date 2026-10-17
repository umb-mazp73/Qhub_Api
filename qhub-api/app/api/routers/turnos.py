import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.application.errors import ApplicationError
from app.domain.models import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CreateTurn,
    Page,
    TurnQuery,
)
from app.application.use_cases.turnos import TurnUseCases
from app.domain.enums import TurnoEstado
from app.api.core.deps import (
    get_agent_context,
    get_tenant_context,
    get_turn_use_cases,
    http_error,
)
from app.api.schemas.turnos import TurnoCrear, TurnoOut

router = APIRouter(prefix="/turnos", tags=["turnos"])


@router.post("", response_model=TurnoOut, status_code=201)
async def crear_turno(
    datos: TurnoCrear,
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    """Saca un turno, en vivo o programado para una franja futura.

    La franja, la numeración y los cupos los resuelve crear_turno_atomico() en una sola
    transacción con lock sobre la cola: calcularlos desde la aplicación tendría una race
    condition real (dos requests concurrentes podrían asignar el mismo número, o entrar
    las dos en la última plaza de una franja)."""
    try:
        turn = await casos.create(context, CreateTurn(datos.cola_id, datos.franja_inicio))
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return TurnoOut.from_domain(turn)


@router.get("/mios", response_model=list[TurnoOut])
async def mis_turnos(
    limite: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Máximo de turnos a devolver"),
    desde: int = Query(0, ge=0, description="Cuántos turnos saltar (para paginar)"),
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    return [
        TurnoOut.from_domain(item)
        for item in await casos.list_mine(context, Page(limite, desde))
    ]


@router.get("", response_model=list[TurnoOut])
async def listar_turnos(
    cola_id: uuid.UUID | None = Query(None),
    estado: TurnoEstado | None = Query(None),
    fecha: date | None = Query(None, description="Filtra por la fecha local de la franja"),
    limite: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Máximo de turnos a devolver"),
    desde: int = Query(0, ge=0, description="Cuántos turnos saltar (para paginar)"),
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    return [
        TurnoOut.from_domain(item)
        for item in await casos.list(
            context, TurnQuery(cola_id, estado, fecha, Page(limite, desde))
        )
    ]


@router.get("/{turno_id}", response_model=TurnoOut)
async def obtener_turno(
    turno_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    try:
        return TurnoOut.from_domain(await casos.get(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{turno_id}/posponer", response_model=TurnoOut)
async def posponer_turno(
    turno_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    """Manda el turno al final de su franja. No lo mueve a otra franja: para eso hay que
    cancelarlo y sacar uno nuevo en la franja deseada, así el cupo se libera de verdad."""
    try:
        return TurnoOut.from_domain(await casos.postpone(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{turno_id}/cancelar", response_model=TurnoOut)
async def cancelar_turno(
    turno_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    """Cancelar libera el cupo de la franja: otro cliente puede tomar ese lugar."""
    try:
        return TurnoOut.from_domain(await casos.cancel(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{turno_id}/atender", response_model=TurnoOut)
async def atender_turno(
    turno_id: uuid.UUID,
    context=Depends(get_agent_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    try:
        return TurnoOut.from_domain(await casos.attend(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{turno_id}/finalizar", response_model=TurnoOut)
async def finalizar_turno(
    turno_id: uuid.UUID,
    context=Depends(get_agent_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    try:
        return TurnoOut.from_domain(await casos.finish(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{turno_id}/no-show", response_model=TurnoOut)
async def marcar_no_show(
    turno_id: uuid.UUID,
    context=Depends(get_agent_context),
    casos: TurnUseCases = Depends(get_turn_use_cases),
):
    """No-show también libera el cupo de la franja: el que no vino no debería seguir
    ocupando un lugar."""
    try:
        return TurnoOut.from_domain(await casos.mark_no_show(context, turno_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc
