from fastapi import APIRouter, Request
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..app_context import AppContext
from .. import errors
from ..api.deps import get_session, require_session
from ..services.session_manager import SessionManager

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupRequest(RequestModel):
    master_password: str
    confirm_master_password: str
    create_recovery_key: bool = False
    language: str = "id"
    weak_password_acknowledged: bool = False
    http_lan_risk_acknowledged: bool = False
    tab_instance_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_label: str = "web"

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        if v not in ("id", "en"):
            raise ValueError("language must be id or en")
        return v


class UnlockRequest(RequestModel):
    master_password: str
    tab_instance_id: str
    client_label: str = "web"


class RecoverRequest(RequestModel):
    recovery_key: str
    new_master_password: str
    confirm_new_master_password: str
    weak_password_acknowledged: bool = False
    tab_instance_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_label: str = "web"


class SessionResult(BaseModel):
    token: str
    session_id: str
    vault_revision: int
    recovery_key: str | None = None


@router.post("/setup")
async def setup(request: Request, body: SetupRequest) -> SessionResult:
    ctx: AppContext = request.app.state.ctx
    if not body.http_lan_risk_acknowledged:
        raise errors.ValidationError("HTTP LAN risk acknowledgement is required")
    result = await ctx.vault.setup(
        body.master_password,
        body.confirm_master_password,
        body.create_recovery_key,
        body.language,
        body.weak_password_acknowledged,
    )
    sm: SessionManager = ctx.sessions
    token = _new_token()
    session = sm.create_session(token, body.tab_instance_id, body.client_label)
    return SessionResult(
        token=token,
        session_id=session.session_id,
        vault_revision=ctx.vault.get_current_revision(),
        recovery_key=result.get("recovery_key"),
    )


@router.post("/sessions/unlock")
async def unlock(request: Request, body: UnlockRequest) -> SessionResult:
    ctx: AppContext = request.app.state.ctx
    if not ctx.vault.setup_completed:
        raise errors.ProblemError("NOT_SETUP", "Not set up", "Vault is not set up", 409)
    await ctx.vault.unlock(body.master_password)
    sm: SessionManager = ctx.sessions
    token = _new_token()
    session = sm.create_session(token, body.tab_instance_id, body.client_label)
    return SessionResult(
        token=token,
        session_id=session.session_id,
        vault_revision=ctx.vault.get_current_revision(),
    )


@router.post("/sessions/recover")
async def recover(request: Request, body: RecoverRequest) -> SessionResult:
    ctx: AppContext = request.app.state.ctx
    new_rec = await ctx.vault.unlock_with_recovery(
        body.recovery_key,
        body.new_master_password,
        body.confirm_new_master_password,
        body.weak_password_acknowledged,
    )
    sm: SessionManager = ctx.sessions
    # invalidate any other live sessions so a recovered vault is single-session
    sm.lock_all()
    token = _new_token()
    session = sm.create_session(token, body.tab_instance_id, body.client_label)
    return SessionResult(
        token=token,
        session_id=session.session_id,
        vault_revision=ctx.vault.get_current_revision(),
        recovery_key=new_rec,
    )


class CurrentSessionResponse(BaseModel):
    session_id: str
    vault_revision: int
    client_label: str


@router.get("/sessions/current")
async def current(request: Request) -> CurrentSessionResponse:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    session = ctx.sessions.get_by_token(token)
    if session is None:
        raise errors.SessionInvalid()
    return CurrentSessionResponse(
        session_id=session.session_id,
        vault_revision=ctx.vault.get_current_revision(),
        client_label=session.client_label,
    )


@router.post("/sessions/lock")
async def lock(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    ctx.sessions.lock_session(token)
    if not ctx.sessions.has_sessions():
        ctx.vault.lock_all()
    return {"locked": True}


@router.post("/sessions/lock-all")
async def lock_all(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return {"locked": True}


@router.post("/sessions/event-ticket")
async def event_ticket(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    ticket = ctx.sessions.issue_ticket(token)
    return {"ticket": ticket}


def _new_token() -> str:
    from ..crypto.csprng import random_bytes

    return random_bytes(32).hex()
