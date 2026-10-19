"""email_query_for: matriz de tabla/columnas/guard según el tipo de dueño (lógica pura).
Sin Supabase ni red: `python -m tests.test_email_resolver` desde qhub-api/ (también pytest)."""
from uuid import uuid4

from app.domain.email_lookup import email_query_for
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import OwnerId, PersonIdentity


def test_usuario_consulta_usuarios_por_id():
    owner_id = uuid4()
    identity = PersonIdentity(OwnerId(PropietarioTipo.USUARIO, owner_id), "ana")
    table, filters = email_query_for(identity)
    assert table == "usuarios"
    assert filters == {"id": str(owner_id)}


def test_empresa_con_uuid_consulta_control_empresas():
    owner_id = uuid4()
    account_id = uuid4()
    identity = PersonIdentity(OwnerId(PropietarioTipo.EMPRESA, owner_id), str(account_id))
    table, filters = email_query_for(identity)
    assert table == "control_empresas"
    assert filters == {"empresa_id": str(owner_id), "id": str(account_id)}


def test_empresa_con_usuario_id_no_uuid_devuelve_none():
    identity = PersonIdentity(OwnerId(PropietarioTipo.EMPRESA, uuid4()), "ana")
    assert email_query_for(identity) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
