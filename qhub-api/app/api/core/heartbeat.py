import asyncio


async def close_safely(websocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def heartbeat(websocket, interval: int) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await websocket.send_json({"tipo": "ping"})
    except asyncio.CancelledError:
        raise
    except Exception:
        await close_safely(websocket, 1011)
