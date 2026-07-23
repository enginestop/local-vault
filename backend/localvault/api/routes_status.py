from fastapi import APIRouter, Request
from pydantic import BaseModel
import socket

from ..app_context import AppContext

router = APIRouter()


class StatusResponse(BaseModel):
    setup_required: bool
    application_version: str
    api_version: str
    schema_version: int
    port: int
    recovery_enabled: bool = False
    http_lan_warning: bool = True
    network_host: str | None = None


@router.get("/status")
async def status(request: Request) -> StatusResponse:
    ctx: AppContext = request.app.state.ctx
    from ..database.pool import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        user_count = await conn.fetchval("SELECT count(*) FROM users")
        owner_id = await conn.fetchval("SELECT id FROM users ORDER BY created_at LIMIT 1")
    return StatusResponse(
        setup_required=user_count == 0,
        application_version="1.0.0",
        api_version="v1",
        schema_version=2,
        port=ctx.config.port,
        network_host=_network_host(),
    )


def _network_host() -> str | None:
    try:
        addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    for address in addresses:
        host = address[4][0]
        if not host.startswith("127."):
            return host
    return None
