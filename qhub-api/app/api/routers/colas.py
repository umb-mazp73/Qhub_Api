import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.application.errors import ApplicationError
from app.domain.models import CreateQueue, QueueChanges, QueueSchedule, UNSET
from app.application.use_cases.colas import QueueUseCases
from app.api.core.deps import (
    get_admin_context,
    get_queue_use_cases,
    get_tenant_context,
    http_error,
)
from app.api.schemas.colas import (
    ColaActualizar,
    ColaCrear,
    ColaEstado,
    ColaOut,
    ColasLimite,
    FranjaOut,
    HorarioActualizar,
    HorarioOut,
)

router = APIRouter(prefix="/colas", tags=["colas"])


@router.post("", response_model=ColaOut, status_code=201)
async def crear_cola(
    datos: ColaCrear,
    context=Depends(get_admin_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Crea una cola para la cuenta del token.

    El límite de colas activas (6 para empresa, 3 para usuario) NO se valida contando acá:
    lo hace un trigger de Postgres (colas_valida_limite) que además toma
    un advisory lock por cuenta, así dos requests simultáneas no pueden colarse las dos
    y dejar a la cuenta por encima del tope. Acá solo se traduce el errcode a 409.

    `rabbitmq_queue_name` y `zona_horaria` también los pone la base (triggers), no la
    aplicación, para que no puedan divergir."""
    command = CreateQueue(
        nombre=datos.nombre,
        descripcion=datos.descripcion,
        hora_apertura=datos.hora_apertura,
        hora_cierre=datos.hora_cierre,
        duracion_franja_minutos=datos.duracion_franja_minutos,
        dias_atencion=tuple(datos.dias_atencion) if datos.dias_atencion is not None else None,
        duracion_turno_minutos=datos.duracion_turno_minutos,
        puestos=datos.puestos,
        capacidad_diaria=datos.capacidad_diaria,
        dias_anticipacion_maxima=datos.dias_anticipacion_maxima,
    )
    try:
        return ColaOut.from_domain(await casos.create(context, command))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.get("", response_model=list[ColaOut])
async def listar_colas(
    activa: bool | None = Query(
        None, description="true: solo las activas · false: solo las eliminadas (archivadas)"
    ),
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Las colas de la cuenta. Sin filtro devuelve también las eliminadas (archivadas),
    marcadas con `activa: false`."""
    return [ColaOut.from_domain(item) for item in await casos.list(context, activa)]


@router.get("/limite", response_model=ColasLimite)
async def limite_colas(
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Cuántas colas puede tener esta cuenta y cuántas le quedan.

    Existe para que el cliente no tenga que descubrir su tope chocándose con un 409:
    los límites dependen del tipo de cuenta (empresa 10, usuario 5) y no son algo que
    quien integra deba adivinar."""
    return ColasLimite.from_domain(await casos.limit(context))


@router.get("/{cola_id}", response_model=ColaOut)
async def obtener_cola(
    cola_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    try:
        return ColaOut.from_domain(await casos.get(context, cola_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{cola_id}", response_model=ColaOut)
async def actualizar_cola(
    cola_id: uuid.UUID,
    datos: ColaActualizar,
    context=Depends(get_admin_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Datos básicos de la cola. El horario se cambia aparte, con
    PUT /colas/{id}/horario."""
    changes = QueueChanges(
        nombre=datos.nombre if "nombre" in datos.model_fields_set else UNSET,
        descripcion=datos.descripcion if "descripcion" in datos.model_fields_set else UNSET,
        activa=datos.activa if "activa" in datos.model_fields_set else UNSET,
    )
    try:
        return ColaOut.from_domain(await casos.update(context, cola_id, changes))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.delete("/{cola_id}", status_code=204)
async def eliminar_cola(
    cola_id: uuid.UUID,
    context=Depends(get_admin_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Soft-delete: pone activa=false, no borra la fila — preserva el historial de
    turnos (el esquema además restringe el DELETE físico con ON DELETE RESTRICT).
    Además libera un lugar contra el límite de colas de la cuenta, porque el trigger
    solo cuenta colas activas."""
    try:
        await casos.deactivate(context, cola_id)
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.get("/{cola_id}/horario", response_model=HorarioOut)
async def obtener_horario(
    cola_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Horario de atención de la cola, más `franjas_por_dia` y `cupos_por_franja`
    derivados — así el cliente ve cómo quedó repartida su capacidad diaria sin tener
    que calcularlo."""
    try:
        return HorarioOut.from_result(await casos.get_schedule(context, cola_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.put("/{cola_id}/horario", response_model=HorarioOut)
async def definir_horario(
    cola_id: uuid.UUID,
    datos: HorarioActualizar,
    context=Depends(get_admin_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Define el horario de atención y las franjas de la cola.

    Es PUT y no PATCH porque el horario es un bloque coherente: la duración de la
    franja, el rango de atención y el cupo diario se validan entre sí, así que se
    reemplaza completo en vez de campo por campo.

    Los turnos YA creados no se mueven: si se recorta el horario, los turnos que
    queden fuera del nuevo rango siguen existiendo con su franja original. Cambiar el
    horario no debería cancelarle el turno a nadie por su cuenta."""
    schedule = QueueSchedule(
        hora_apertura=datos.hora_apertura,
        hora_cierre=datos.hora_cierre,
        duracion_franja_minutos=datos.duracion_franja_minutos,
        dias_atencion=tuple(datos.dias_atencion),
        duracion_turno_minutos=datos.duracion_turno_minutos,
        puestos=datos.puestos,
        capacidad_diaria=datos.capacidad_diaria,
        dias_anticipacion_maxima=datos.dias_anticipacion_maxima,
        zona_horaria=datos.zona_horaria,
    )
    try:
        return HorarioOut.from_result(
            await casos.replace_schedule(context, cola_id, schedule)
        )
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.get("/{cola_id}/franjas", response_model=list[FranjaOut])
async def listar_franjas(
    cola_id: uuid.UUID,
    fecha: date | None = Query(
        None, description="Día a consultar (YYYY-MM-DD). Por default, hoy en la zona de la cola."
    ),
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """El calendario de la cola para un día: cada franja con sus cupos, cuántos están
    ocupados y cuántos quedan.

    Devuelve una lista vacía si la fecha no es un día de atención de la cola.

    `ocupados` cuenta los turnos que consumieron un cupo: todos menos los cancelados y
    los no-show, que lo liberan. El cálculo lo hace la función listar_franjas() de
    Postgres, que es la misma fuente de verdad que usa crear_turno_atomico para decidir
    si una franja está llena — así lo que muestra el calendario nunca contradice lo que
    permite la creación de turnos."""
    try:
        return [FranjaOut.from_domain(item) for item in await casos.list_slots(context, cola_id, fecha)]
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.get("/{cola_id}/estado", response_model=ColaEstado)
async def estado_cola(
    cola_id: uuid.UUID,
    context=Depends(get_tenant_context),
    casos: QueueUseCases = Depends(get_queue_use_cases),
):
    """Cuántos turnos hay esperando y cuántos se están atendiendo en la cola.

    No incluye cupos: eso depende de la franja, y vive en GET /colas/{id}/franjas."""
    try:
        return ColaEstado.from_domain(await casos.state(context, cola_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc
