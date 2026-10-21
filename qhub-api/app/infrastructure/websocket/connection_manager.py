from uuid import UUID

from fastapi import WebSocket

from app.domain.models import QueueEventEnvelope
from app.domain.enums import PropietarioTipo
from app.domain.value_objects import PersonIdentity

UserKey = tuple[str, str, str]


def user_key(
    owner_type: PropietarioTipo | str,
    owner_id: UUID | str,
    user_id: str,
) -> UserKey:
    return (
        PropietarioTipo(owner_type).value,
        str(owner_id),
        str(user_id),
    )


class ConnectionManager:
    def __init__(self) -> None:
        self._conexiones: dict[UUID, list[WebSocket]] = {}
        self._conexiones_usuario: dict[UserKey, list[WebSocket]] = {}

    async def connect(
        self,
        queue_id: UUID,
        websocket: WebSocket,
        ya_aceptado: bool = False,
    ) -> None:
        if not ya_aceptado:
            await websocket.accept()
        self._conexiones.setdefault(queue_id, []).append(websocket)

    def disconnect(self, queue_id: UUID, websocket: WebSocket) -> None:
        sockets = self._conexiones.get(queue_id)
        if not sockets:
            return
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._conexiones.pop(queue_id, None)

    async def send_queue_event(
        self, queue_id: UUID, event: QueueEventEnvelope
    ) -> int:
        if queue_id != event.queue_id:
            raise ValueError("queue_id no coincide con el evento")
        frame = event.to_wire()
        delivered = 0
        for websocket in list(self._conexiones.get(queue_id, ())):
            try:
                await websocket.send_json(frame)
                delivered += 1
            except Exception:
                self.disconnect(queue_id, websocket)
        return delivered

    async def connect_usuario(
        self,
        propietario_tipo: PropietarioTipo | str,
        propietario_id: UUID | str,
        usuario_id: str,
        websocket: WebSocket,
        ya_aceptado: bool = False,
    ) -> None:
        if not ya_aceptado:
            await websocket.accept()
        key = user_key(propietario_tipo, propietario_id, usuario_id)
        self._conexiones_usuario.setdefault(key, []).append(websocket)

    def disconnect_usuario(
        self,
        propietario_tipo: PropietarioTipo | str,
        propietario_id: UUID | str,
        usuario_id: str,
        websocket: WebSocket,
    ) -> None:
        key = user_key(propietario_tipo, propietario_id, usuario_id)
        sockets = self._conexiones_usuario.get(key)
        if not sockets:
            return
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._conexiones_usuario.pop(key, None)

    async def enviar_a_usuario(
        self,
        propietario_tipo: PropietarioTipo | str,
        propietario_id: UUID | str,
        usuario_id: str,
        mensaje: dict,
    ) -> int:
        key = user_key(propietario_tipo, propietario_id, usuario_id)
        delivered = 0
        for websocket in list(self._conexiones_usuario.get(key, ())):
            try:
                await websocket.send_json(mensaje)
                delivered += 1
            except Exception:
                self.disconnect_usuario(*key, websocket)
        return delivered

    async def send(self, target, message) -> int:
        if isinstance(target, PersonIdentity):
            return await self.enviar_a_usuario(
                target.owner.tipo,
                target.owner.id,
                target.usuario_id,
                message.to_wire(),
            )
        queue_id = UUID(str(target))
        return await self.send_queue_event(queue_id, message)
