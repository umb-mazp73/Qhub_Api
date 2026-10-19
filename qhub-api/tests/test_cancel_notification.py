"""TurnUseCases.cancel crea un aviso "turno_cancelado" para el dueño del turno.
Sin dependencias extra: `python -m tests.test_cancel_notification` desde qhub-api/ (también pytest)."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4

from app.application.use_cases.turnos import TurnUseCases
from app.domain.entities import Turno
from app.domain.enums import PropietarioTipo, TurnoEstado
from app.domain.value_objects import OwnerId, PersonIdentity, TenantContext

OWNER = OwnerId(PropietarioTipo("empresa"), uuid4())
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)


def turn(usuario_id: str = "ana") -> Turno:
    return Turno(id=uuid4(), cola_id=uuid4(), owner=OWNER, propietario_nombre="x", usuario_id=usuario_id,
                 franja_inicio=NOW, franja_fecha=date(2026, 10, 17), programado=False, numero=7,
                 estado=TurnoEstado.EN_ESPERA, posicion=1, hora_creacion=NOW, hora_atencion=None,
                 hora_finalizacion=None, agente_id=None, recordatorio_enviado_en=None)


class Repo:
    def __init__(self, *turns):
        self.turns = {t.id: t for t in turns}

    async def get(self, owner, turn_id):
        return self.turns.get(turn_id)

    async def compact_waiting_positions(self, *a):
        pass

    async def set_state(self, owner, turn_id, state, **kw):
        self.turns[turn_id] = replace(self.turns[turn_id], estado=state)
        return self.turns[turn_id]


class EventSink:
    async def publish(self, *a, **k):
        pass


class NotificationSink:
    def __init__(self):
        self.requested = []

    async def request(self, command):
        self.requested.append(command)


class Clock:
    def now_utc(self):
        return NOW


def ctx(user, rol):
    return TenantContext(PersonIdentity(OWNER, user), rol)


def run(coro):
    return asyncio.run(coro)


def test_cancel_crea_aviso_turno_cancelado():
    t = turn("ana")
    sink = NotificationSink()
    uc = TurnUseCases(Repo(t), None, EventSink(), sink, Clock(), enforce_ownership=False)
    run(uc.cancel(ctx("ana", "cliente"), t.id))
    assert len(sink.requested) == 1
    cmd = sink.requested[0]
    assert cmd.notice_type == "turno_cancelado"
    assert cmd.turn_id == t.id
    assert cmd.identity.owner == OWNER
    assert cmd.identity.usuario_id == "ana"
    assert "7" in cmd.message


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
