import uuid
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from ..app_context import AppContext
from .. import errors
from ..api.deps import get_session, require_session
from ..services.session_manager import SessionManager
from ..services.auth_service import register as auth_register, authenticate, get_user_by_id
from ..services.multitenant_service import ensure_user_vaults
from ..domain.password_policy import validate_master_password, PasswordPolicyError

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(RequestModel):
    username: str
    email: str
    master_password: str
    confirm_master_password: str
    weak_password_acknowledged: bool = False
    http_lan_risk_acknowledged: bool = False
    create_recovery_key: bool = False
    language: str = "id"
    tab_instance_id: str = str(uuid.uuid4())
    client_label: str = "web"


class LoginRequest(RequestModel):
    login: str
    master_password: str
    tab_instance_id: str
    client_label: str = "web"


class SessionResult(BaseModel):
    token: str = ""
    session_id: str = ""
    user_id: str
    username: str
    email: str
    recovery_key: str | None = None
    role: str = "admin_user"
    account_status: str = "active"
    message: str | None = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request, body: RegisterRequest) -> SessionResult:
    ctx: AppContext = request.app.state.ctx
    username = body.username.strip()
    email = body.email.strip().lower()
    if not username:
        raise errors.ValidationError("Username must not be empty")
    if not email:
        raise errors.ValidationError("Email must not be empty")
    if not body.http_lan_risk_acknowledged:
        raise errors.ValidationError("HTTP LAN risk acknowledgement is required")
    try:
        validate_master_password(
            body.master_password,
            body.confirm_master_password,
            body.weak_password_acknowledged,
        )
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    user = await auth_register(
        username=username,
        email=email,
        master_password=body.master_password,
    )
    if user.account_status == "pending":
        return SessionResult(user_id=str(user.id), username=user.username, email=user.email, role=user.role, account_status=user.account_status, message="Menunggu persetujuan Superadmin.")
    vault = await ctx.vault.setup(
        user.id,
        body.master_password,
        body.create_recovery_key,
        body.language if body.language in {"id", "en"} else "id",
    )
    await ensure_user_vaults(user.id, body.master_password, body.language)
    sm: SessionManager = ctx.sessions
    token = _new_token()
    session = sm.create_session(token, body.tab_instance_id, body.client_label, user.id)
    return SessionResult(
        token=token,
        session_id=session.session_id,
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        recovery_key=vault.get("recovery_key"),
        role=user.role, account_status=user.account_status,
    )


class LegacySetupRequest(RequestModel):
    master_password: str
    confirm_master_password: str
    create_recovery_key: bool = False
    language: str = "id"
    weak_password_acknowledged: bool = False
    http_lan_risk_acknowledged: bool = False
    tab_instance_id: str = str(uuid.uuid4())
    client_label: str = "web"


async def _legacy_user(request: Request):
    from ..database.pool import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, email FROM users ORDER BY created_at LIMIT 1"
        )
    return row


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def legacy_setup(request: Request, body: LegacySetupRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    if not body.http_lan_risk_acknowledged:
        raise errors.ValidationError("HTTP LAN risk acknowledgement is required")
    try:
        validate_master_password(body.master_password, body.confirm_master_password, body.weak_password_acknowledged)
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    existing = await _legacy_user(request)
    if existing is not None:
        raise errors.SetupAlreadyCompleted()
    user = await auth_register("local-owner", "local-owner@localhost", body.master_password)
    result = await ctx.vault.setup(user.id, body.master_password, body.create_recovery_key, body.language)
    token = _new_token()
    session = ctx.sessions.create_session(token, body.tab_instance_id, body.client_label, user.id)
    return {"token": token, "session_id": session.session_id, "vault_revision": 1, **result}


@router.post("/sessions/login")
async def login(request: Request, body: LoginRequest) -> SessionResult:
    ctx: AppContext = request.app.state.ctx
    user = await authenticate(body.login, body.master_password)
    try:
        await ctx.vault.unlock(user.id, body.master_password)
    except errors.ProblemError as exc:
        # Accounts registered while approval was required did not have a
        # vault yet.  Once approved, the first successful login has the
        # plaintext master password needed to create it safely.
        if exc.code != "VAULT_NOT_FOUND":
            raise
        await ctx.vault.setup(user.id, body.master_password, False, "id")
    await ensure_user_vaults(user.id, body.master_password)
    sm: SessionManager = ctx.sessions
    token = _new_token()
    session = sm.create_session(token, body.tab_instance_id, body.client_label, user.id)
    return SessionResult(
        token=token,
        session_id=session.session_id,
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role, account_status=user.account_status,
    )


class LegacyUnlockRequest(RequestModel):
    master_password: str
    tab_instance_id: str
    client_label: str = "web"


@router.post("/sessions/unlock")
async def legacy_unlock(request: Request, body: LegacyUnlockRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_row = await _legacy_user(request)
    if user_row is None:
        raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
    user = await authenticate(user_row["username"], body.master_password)
    await ctx.vault.unlock(user.id, body.master_password)
    token = _new_token()
    session = ctx.sessions.create_session(token, body.tab_instance_id, body.client_label, user.id)
    return {"token": token, "session_id": session.session_id, "vault_revision": await ctx.vault.get_current_revision(user.id)}


class LegacyRecoverRequest(RequestModel):
    recovery_key: str
    new_master_password: str
    confirm_new_master_password: str
    weak_password_acknowledged: bool = False
    tab_instance_id: str
    client_label: str = "web"


@router.post("/sessions/recover")
async def legacy_recover(request: Request, body: LegacyRecoverRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_row = await _legacy_user(request)
    if user_row is None:
        raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    user = await ctx.vault.unlock_with_recovery(
        str(user_row["id"]), body.recovery_key, body.new_master_password,
        body.confirm_new_master_password, body.weak_password_acknowledged,
    )
    from ..services.auth_service import set_master_password
    await set_master_password(str(user_row["id"]), body.new_master_password)
    token = _new_token()
    session = ctx.sessions.create_session(token, body.tab_instance_id, body.client_label, str(user_row["id"]))
    return {"token": token, "session_id": session.session_id, "vault_revision": await ctx.vault.get_current_revision(str(user_row["id"])), "recovery_key": user}


class CurrentSessionResponse(BaseModel):
    session_id: str
    user_id: str
    username: str
    email: str
    client_label: str
    role: str
    account_status: str


@router.get("/sessions/current")
async def current(request: Request) -> CurrentSessionResponse:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    session = ctx.sessions.get_by_token(token)
    if session is None:
        raise errors.SessionInvalid()
    user = await get_user_by_id(session.user_id)
    if user is None:
        raise errors.SessionInvalid()
    if user.account_status == "pending":
        raise errors.AccountPending()
    if user.account_status == "disabled":
        raise errors.AccountDisabled()
    return CurrentSessionResponse(
        session_id=session.session_id,
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        client_label=session.client_label,
        role=user.role, account_status=user.account_status,
    )


@router.post("/sessions/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    session = ctx.sessions.get_by_token(token)
    ctx.sessions.lock_session(token)
    if session is not None and session.user_id and not any(
        active is not None and active.user_id == session.user_id
        for session_id in ctx.sessions.active_session_ids()
        for active in [ctx.sessions.get_by_id(session_id)]
    ):
        ctx.vault.lock_user(session.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/lock", status_code=status.HTTP_204_NO_CONTENT)
async def lock(request: Request) -> Response:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    session = ctx.sessions.get_by_token(token)
    ctx.sessions.lock_session(token)
    if session is not None and session.user_id and not any(
        active.user_id == session.user_id
        for active in (ctx.sessions.get_by_id(session_id) for session_id in ctx.sessions.active_session_ids())
        if active is not None
    ):
        ctx.vault.lock_user(session.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/lock-all", status_code=status.HTTP_204_NO_CONTENT)
async def lock_all(request: Request) -> Response:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/event-ticket")
async def event_ticket(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    token = get_session(request)
    ticket = ctx.sessions.issue_ticket(token)
    return {"ticket": ticket}


def _new_token() -> str:
    from ..crypto.csprng import random_bytes
    return random_bytes(32).hex()
