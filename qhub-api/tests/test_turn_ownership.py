"""ENFORCE_TURN_OWNERSHIP: quien no es admin/agente solo ve, cancela y pospone sus turnos (ajeno → 404).
Sin dependencias extra: `python -m tests.test_turn_ownership` desde qhub-api/ (también corre bajo pytest)."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4

from app.application.errors import NotFound
from app.application.use_cases.turnos import TurnUseCases
from app.domain.entities import Turno
from app.domain.enums import PropietarioTipo, TurnoEstado
from app.domain.models import TurnQuery
from app.domain.value_objects import OwnerId, PersonIdentity, TenantContext

OWNER = OwnerId(PropietarioTipo("empresa"), uuid4())
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)


def turn(usuario_id: str) -> Turno:
    return Turno(id=uuid4(), cola_id=uuid4(), owner=OWNER, propietario_nombre="x", usuario_id=usuario_id, franja_inicio=NOW, franja_fecha=date(2026, 10, 17),
                 programado=False, numero=1, estado=TurnoEstado.EN_ESPERA, posicion=1, hora_creacion=NOW, hora_atencion=None, hora_finalizacion=None, agente_id=None, recordatorio_enviado_en=None)


class Repo:
    def __init__(self, *turns): self.turns = {t.id: t for t in turns}
    async def get(self, owner, turn_id): return self.turns.get(turn_id)
    async def list(self, owner, query): return tuple(self.turns.values())
    async def last_waiting_position(self, owner, t): return 1
    async def set_position(self, *a): pass
    async def compact_waiting_positions(self, *a): pass
    async def set_state(self, owner, turn_id, state, **kw):
        self.turns[turn_id] = replace(self.turns[turn_id], estado=state); return self.turns[turn_id]


class Sink:
    async def publish(self, *a, **k): pass
    async def request(self, *a, **k): pass


class Clock:
    def now_utc(self): return NOW


def usecases(repo, enforce): return TurnUseCases(repo, None, Sink(), Sink(), Clock(), enforce_ownership=enforce)
def ctx(user, rol): return TenantContext(PersonIdentity(OWNER, user), rol)


def run(coro): return asyncio.run(coro)


def raises_not_found(coro) -> bool:
    try: run(coro)
    except NotFound: return True
    return False


def test_con_ownership_el_turno_ajeno_es_404():
    mine, theirs = turn("ana"), turn("luis")
    uc = usecases(Repo(mine, theirs), True)
    assert run(uc.get(ctx("ana", "cliente"), mine.id)).id == mine.id
    assert raises_not_found(uc.get(ctx("ana", "cliente"), theirs.id))
    assert raises_not_found(uc.cancel(ctx("ana", "cliente"), theirs.id))
    assert raises_not_found(uc.postpone(ctx("ana", "cliente"), theirs.id))
    assert run(uc.cancel(ctx("ana", "cliente"), mine.id)).estado == TurnoEstado.CANCELADO


def test_personal_ve_y_opera_todo():
    t = turn("luis")
    for rol in ("admin", "agente"):
        assert run(usecases(Repo(t), True).get(ctx("ana", rol), t.id)).id == t.id


def test_listado_de_un_cliente_solo_trae_los_suyos():
    mine, theirs = turn("ana"), turn("luis")
    uc = usecases(Repo(mine, theirs), True)
    assert [t.usuario_id for t in run(uc.list(ctx("ana", "cliente"), TurnQuery(None, None, None)))] == ["ana"]
    assert len(run(uc.list(ctx("ana", "agente"), TurnQuery(None, None, None)))) == 2


def test_apagado_por_defecto_no_cambia_nada():
    theirs = turn("luis")
    uc = usecases(Repo(theirs), False)
    assert run(uc.get(ctx("ana", "cliente"), theirs.id)).id == theirs.id
    assert len(run(uc.list(ctx("ana", "cliente"), TurnQuery(None, None, None)))) == 1
    assert run(TurnUseCases(Repo(theirs), None, Sink(), Sink(), Clock()).get(ctx("ana", "cliente"), theirs.id)).id == theirs.id   # sin el parámetro


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
