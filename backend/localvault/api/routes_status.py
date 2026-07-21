from fastapi import APIRouter, Request, Header
from pydantic import BaseModel

from ..app_context import AppContext
from .. import errors
from ..api.deps import get_session
from ..services.session_manager import SessionManager

router = APIRouter()


class StatusResponse(BaseModel):
    setup_required: bool
    application_version: str
    api_version: str
    schema_version: int
    recovery_enabled: bool
    port: int
    http_lan_warning: bool = True


@router.get("/status")
async def status(request: Request) -> StatusResponse:
    ctx: AppContext = request.app.state.ctx
    recovery_enabled = False
    if ctx.vault.setup_completed:
        row = ctx.conn.execute(
            "SELECT recovery_wrap_nonce FROM vault_envelope WHERE id = 1"
        ).fetchone()
        recovery_enabled = row is not None and row["recovery_wrap_nonce"] is not None
    return StatusResponse(
        setup_required=not ctx.vault.setup_completed,
        application_version="1.0.0",
        api_version="v1",
        schema_version=1,
        recovery_enabled=recovery_enabled,
        port=ctx.config.port,
    )
