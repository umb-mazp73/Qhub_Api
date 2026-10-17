from uuid import UUID

from app.domain.models import CreateTurn, Page, TurnQuery
from app.domain.interfaces.turns import TurnRepository
from app.domain.entities import Turno
from app.domain.enums import TurnoEstado
from app.domain.value_objects import OwnerId, PersonIdentity, TenantContext
from app.infrastructure.persistence.supabase.error_mapping import map_turn_rpc_error
from app.infrastructure.persistence.supabase.mappers import turno_from_row


def _paginated(request, page: Page):
    """Orden total (franja, número, id): sin desempates, dos páginas podrían repetir o
    saltarse filas con la misma franja."""
    return (
        request.order("franja_inicio")
        .order("numero")
        .order("id")
        .range(page.offset, page.offset + page.limit - 1)
    )


class SupabaseTurnRepository(TurnRepository):
    def __init__(self, client) -> None:
        self._client = client

    def _owned(self, owner: OwnerId):
        return (
            self._client.table("turnos")
            .select("*")
            .eq("propietario_tipo", owner.tipo.value)
            .eq("propietario_id", str(owner.id))
        )

    async def get(self, owner: OwnerId, turn_id: UUID) -> Turno | None:
        result = await self._owned(owner).eq("id", str(turn_id)).limit(1).execute()
        return turno_from_row(result.data[0]) if result.data else None

    async def list(self, owner: OwnerId, query: TurnQuery) -> tuple[Turno, ...]:
        request = self._owned(owner)
        if query.cola_id is not None:
            request = request.eq("cola_id", str(query.cola_id))
        if query.estado is not None:
            request = request.eq("estado", query.estado.value)
        if query.fecha is not None:
            request = request.eq("franja_fecha", query.fecha.isoformat())
        result = await _paginated(request, query.page).execute()
        return tuple(turno_from_row(row) for row in result.data)

    async def list_for_person(
        self, identity: PersonIdentity, page: Page
    ) -> tuple[Turno, ...]:
        request = self._owned(identity.owner).eq("usuario_id", identity.usuario_id)
        result = await _paginated(request, page).execute()
        return tuple(turno_from_row(row) for row in result.data)

    async def create_atomic(
        self, context: TenantContext, command: CreateTurn
    ) -> Turno:
        owner = context.identity.owner
        try:
            result = await self._client.rpc(
                "crear_turno_atomico",
                {
                    "p_cola_id": str(command.cola_id),
                    "p_propietario_tipo": owner.tipo.value,
                    "p_propietario_id": str(owner.id),
                    "p_usuario_id": context.identity.usuario_id,
                    "p_franja_inicio": (
                        command.franja_inicio.isoformat()
                        if command.franja_inicio is not None
                        else None
                    ),
                },
            ).execute()
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise map_turn_rpc_error(exc) from exc
            raise
        return turno_from_row(result.data)

    async def last_waiting_position(self, owner: OwnerId, turn: Turno) -> int:
        result = (
            await self._client.table("turnos")
            .select("posicion")
            .eq("propietario_tipo", owner.tipo.value)
            .eq("propietario_id", str(owner.id))
            .eq("cola_id", str(turn.cola_id))
            .eq("franja_inicio", turn.franja_inicio.isoformat())
            .eq("estado", TurnoEstado.EN_ESPERA.value)
            .order("posicion", desc=True)
            .limit(1)
            .execute()
        )
        return int(result.data[0]["posicion"]) if result.data else 0

    async def set_position(
        self, owner: OwnerId, turn_id: UUID, position: int
    ) -> None:
        await self._client.table("turnos").update({"posicion": position}).eq(
            "propietario_tipo", owner.tipo.value
        ).eq("propietario_id", str(owner.id)).eq("id", str(turn_id)).execute()

    async def set_state(
        self,
        owner: OwnerId,
        turn_id: UUID,
        state: TurnoEstado,
        attended_at=None,
        finished_at=None,
        agent_id: str | None = None,
    ) -> Turno:
        values = {"estado": state.value}
        if attended_at is not None:
            values["hora_atencion"] = attended_at.isoformat()
        if finished_at is not None:
            values["hora_finalizacion"] = finished_at.isoformat()
        if agent_id is not None:
            values["agente_id"] = agent_id
        result = (
            await self._client.table("turnos")
            .update(values)
            .eq("propietario_tipo", owner.tipo.value)
            .eq("propietario_id", str(owner.id))
            .eq("id", str(turn_id))
            .execute()
        )
        return turno_from_row(result.data[0])

    async def compact_waiting_positions(
        self, owner: OwnerId, queue_id: UUID, slot_start
    ) -> None:
        result = (
            await self._client.table("turnos")
            .select("id, posicion")
            .eq("propietario_tipo", owner.tipo.value)
            .eq("propietario_id", str(owner.id))
            .eq("cola_id", str(queue_id))
            .eq("franja_inicio", slot_start.isoformat())
            .eq("estado", TurnoEstado.EN_ESPERA.value)
            .order("posicion")
            .execute()
        )
        for expected, row in enumerate(result.data, start=1):
            if row["posicion"] != expected:
                await self._client.table("turnos").update(
                    {"posicion": expected}
                ).eq("propietario_tipo", owner.tipo.value).eq(
                    "propietario_id", str(owner.id)
                ).eq("id", row["id"]).execute()
