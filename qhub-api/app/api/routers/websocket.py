import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.core.deps import context_from_claims, owner_from_claims
from app.api.core.heartbeat import heartbeat
from app.api.core.websocket_auth import resolver_token_websocket
from app.domain.value_objects import PersonIdentity

logger = logging.getLogger("qhub_api.websocket")
router = APIRouter(tags=["websocket"])


async def _token(websocket: WebSocket, token: str | None) -> str | None:
    if token is not None:
        return token
    try:
        return await websocket.receive_text()
    except WebSocketDisconnect:
        return None


@router.websocket("/ws/turnos/{cola_id}")
async def ws_turnos(
    websocket: WebSocket,
    cola_id: UUID,
    token: str | None = Query(None),
):
    """Eventos en vivo de una cola. Cierra con 4401 si el token es inválido o si la cola
    no es de la cuenta del token (sin distinguir los dos casos)."""
    await websocket.accept()
    token = await _token(websocket, token)
    if token is None:
        return
    container = websocket.app.state.container
    try:
        user = await resolver_token_websocket(token)
        await container.queues.get(context_from_claims(user), cola_id)
    except Exception:
        await websocket.close(code=4401)
        return

    manager = container.resources.websocket_manager
    await manager.connect(cola_id, websocket, ya_aceptado=True)
    task = asyncio.create_task(
        heartbeat(websocket, container.settings.WS_HEARTBEAT_INTERVAL)
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        finally:
            manager.disconnect(cola_id, websocket)


@router.websocket("/ws/notificaciones")
async def ws_notificaciones(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    """Avisos personales en vivo, aislados por cuenta + usuario."""
    await websocket.accept()
    token = await _token(websocket, token)
    if token is None:
        return
    container = websocket.app.state.container
    try:
        user = await resolver_token_websocket(token)
        identity = PersonIdentity(owner_from_claims(user), user["usuario_id"])
    except Exception:
        await websocket.close(code=4401)
        return

    manager = container.resources.websocket_manager
    key = (identity.owner.tipo, identity.owner.id, identity.usuario_id)
    await manager.connect_usuario(*key, websocket, ya_aceptado=True)
    task = asyncio.create_task(
        heartbeat(websocket, container.settings.WS_HEARTBEAT_INTERVAL)
    )
    try:
        try:
            unread = await container.notifications.count_unread(identity)
        except Exception:
            logger.exception("No se pudo contar las notificaciones no leídas")
            unread = None
        await websocket.send_json(
            {
                "tipo": "conectado",
                "usuario_id": identity.usuario_id,
                "no_leidas": unread,
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        try:
            await asyncio.gather(task, return_exceptions=True)
        finally:
            manager.disconnect_usuario(*key, websocket)
