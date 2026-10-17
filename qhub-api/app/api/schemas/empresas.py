import uuid
from datetime import datetime

from pydantic import BaseModel


class EmpresaCrear(BaseModel):
    nombre: str


class EmpresaActualizar(BaseModel):
    nombre: str | None = None
    activa: bool | None = None


class EmpresaOut(BaseModel):
    id: uuid.UUID
    nombre: str
    activa: bool
    creada_en: datetime


class EmpresaConApiKey(EmpresaOut):
    api_key: str
