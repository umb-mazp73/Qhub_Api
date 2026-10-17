import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.domain.enums import PropietarioTipo


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RegistroCrear(BaseModel):
    """Datos de registro, comunes a los dos tipos de cuenta.

    `tipo_cuenta` decide qué se crea:
      * "empresa" → la entidad `empresas` + su primera fila en `control_empresas`
                    (requiere `nombre_empresa`)
      * "usuario" → una cuenta individual en `usuarios` (ignora `nombre_empresa`)

    Caso especial: si la request llega CON sesión iniciada (Authorization: Bearer) y
    tipo_cuenta="empresa", no se crea una empresa nueva — se agrega una cuenta más a la
    empresa del token. Así una empresa ya registrada nunca se duplica."""

    tipo_cuenta: Literal["empresa", "usuario"] = "empresa"
    nombre_empresa: str | None = Field(default=None, min_length=1, max_length=200)
    nombre: str = Field(min_length=1, max_length=100)
    apellido: str = Field(min_length=1, max_length=100)
    nombre_usuario: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    pais: str = Field(min_length=1, max_length=100)
    ciudad: str = Field(min_length=1, max_length=100)
    acepto_terminos: bool

    @field_validator("acepto_terminos")
    @classmethod
    def _debe_aceptar_terminos(cls, valor: bool) -> bool:
        if not valor:
            raise ValueError("Hay que aceptar los términos y condiciones para registrarse")
        return valor

    @field_validator("nombre_usuario")
    @classmethod
    def _usuario_sin_espacios(cls, valor: str) -> str:
        if " " in valor:
            raise ValueError("nombre_usuario no puede contener espacios")
        return valor


class RegistroOut(BaseModel):
    """Nunca devuelve la password ni su hash.

    `propietario_tipo`/`propietario_id` son la identidad de la cuenta que hay que usar
    de ahí en adelante (es lo que va firmado dentro del access_token), y `limite_colas`
    se informa para que el cliente sepa su tope sin tener que adivinarlo."""

    propietario_tipo: PropietarioTipo
    propietario_id: uuid.UUID
    nombre_usuario: str
    email: str
    nombre_empresa: str | None = None
    limite_colas: int
    creada_en: datetime


class LoginCrear(BaseModel):
    identificador: str = Field(min_length=1, description="email o nombre_usuario")
    password: str = Field(min_length=1)
