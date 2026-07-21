from typing import Optional
from fastapi import Request, Header
from .. import errors
from ..services.session_manager import SessionManager
from ..services.auth_service import get_user_by_id


def get_request_id(request: Request, x_request_id: Optional[str] = Header(None)) -> str:
    import uuid
    rid = x_request_id or str(uuid.uuid4())
    request.state.request_id = rid
    return rid


def get_session(request: Request) -> str:
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise errors.SessionInvalid()
    token = auth[7:].strip()
    return token


def require_session(request: Request):
    from ..app_context import AppContext
    from ..services.session_manager import Session
    token = get_session(request)
    ctx: AppContext = request.app.state.ctx
    session = ctx.sessions.get_by_token(token)
    if session is None:
        raise errors.SessionInvalid()
    return session


async def require_user(request: Request):
    session = require_session(request)
    user = await get_user_by_id(session.user_id)
    if user is None:
        raise errors.SessionInvalid()
    return user


def get_user_id(request: Request) -> str:
    from ..app_context import AppContext
    token = get_session(request)
    ctx: AppContext = request.app.state.ctx
    session = ctx.sessions.get_by_token(token)
    if session is None or session.user_id is None:
        raise errors.SessionInvalid()
    return session.user_id
