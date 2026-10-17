import uuid

from fastapi import APIRouter, Depends, Query

from app.api.core.security import verificar_admin
from app.application.errors import ApplicationError
from app.domain.models import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CreateEmpresa,
    EmpresaChanges,
    Page,
    UNSET,
)
from app.application.use_cases.empresas import EmpresaUseCases
from app.domain.entities import Empresa
from app.api.core.deps import get_empresa_use_cases, http_error
from app.api.schemas.empresas import (
    EmpresaActualizar,
    EmpresaConApiKey,
    EmpresaCrear,
    EmpresaOut,
)

router = APIRouter(
    prefix="/empresas", tags=["empresas"], dependencies=[Depends(verificar_admin)]
)


def _out(empresa: Empresa) -> EmpresaOut:
    return EmpresaOut(
        id=empresa.id,
        nombre=empresa.nombre,
        activa=empresa.activa,
        creada_en=empresa.creada_en,
    )


@router.post("", response_model=EmpresaConApiKey, status_code=201)
async def crear_empresa(
    datos: EmpresaCrear,
    casos: EmpresaUseCases = Depends(get_empresa_use_cases),
):
    result = await casos.create(CreateEmpresa(datos.nombre))
    return EmpresaConApiKey(**_out(result.empresa).model_dump(), api_key=result.api_key)


@router.get("", response_model=list[EmpresaOut])
async def listar_empresas(
    limite: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    desde: int = Query(0, ge=0),
    casos: EmpresaUseCases = Depends(get_empresa_use_cases),
):
    return [_out(item) for item in await casos.list_all(Page(limite, desde))]


@router.get("/{empresa_id}", response_model=EmpresaOut)
async def obtener_empresa(
    empresa_id: uuid.UUID,
    casos: EmpresaUseCases = Depends(get_empresa_use_cases),
):
    try:
        return _out(await casos.get(empresa_id))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.patch("/{empresa_id}", response_model=EmpresaOut)
async def actualizar_empresa(
    empresa_id: uuid.UUID,
    datos: EmpresaActualizar,
    casos: EmpresaUseCases = Depends(get_empresa_use_cases),
):
    changes = EmpresaChanges(
        nombre=datos.nombre if "nombre" in datos.model_fields_set else UNSET,
        activa=datos.activa if "activa" in datos.model_fields_set else UNSET,
    )
    try:
        return _out(await casos.update(empresa_id, changes))
    except ApplicationError as exc:
        raise http_error(exc) from exc


@router.post("/{empresa_id}/rotar-api-key", response_model=EmpresaConApiKey)
async def rotar_api_key(
    empresa_id: uuid.UUID,
    casos: EmpresaUseCases = Depends(get_empresa_use_cases),
):
    """Revoca las keys activas de la empresa y emite una nueva.

    El orden importa: primero revocar, después emitir. Si se hiciera al revés, la
    revocación en bloque ("todas las activas de esta empresa") desactivaría también la
    key recién creada."""
    try:
        result = await casos.rotate_api_key(empresa_id)
    except ApplicationError as exc:
        raise http_error(exc) from exc
    return EmpresaConApiKey(**_out(result.empresa).model_dump(), api_key=result.api_key)
