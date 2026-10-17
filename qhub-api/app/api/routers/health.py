from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["salud"])


@router.get("/")
async def salud(request: Request):
    """Liveness: el proceso está vivo. No consulta dependencias."""
    return {"status": "ok", "app": request.app.state.container.settings.APP_NAME}


@router.get("/listo")
async def listo(request: Request):
    """Readiness: el proceso puede atender de verdad (Supabase responde y, si hay broker
    configurado, también RabbitMQ). Responde 503 si no, para que un balanceador saque a
    esta instancia de rotación sin matarla."""
    container = request.app.state.container
    estado: dict[str, str] = {}
    try:
        await container.supabase.require_client().table("empresas").select("id").limit(1).execute()
        estado["supabase"] = "ok"
    except Exception:
        estado["supabase"] = "caido"

    if not container.rabbit.enabled:
        estado["rabbitmq"] = "deshabilitado"
    else:
        try:
            await container.rabbit.get_connection()
            estado["rabbitmq"] = "ok"
        except Exception:
            estado["rabbitmq"] = "caido"

    listo_ = "caido" not in estado.values()
    return JSONResponse(status_code=200 if listo_ else 503, content=estado)
