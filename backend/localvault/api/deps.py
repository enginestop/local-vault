from typing import Optional
from fastapi import Request, Header
from .. import errors
from ..services.session_manager import SessionManager


def get_request_id(request: Request, x_request_id: Optional[str] = Header(None)) -> str:
    import uuid

    rid = x_request_id or str(uuid.uuid4())
    request.state.request_id = rid
    return rid


def get_session(request: Request) -> str:
    """Extract Bearer token; raise 401 if missing/invalid format."""
    auth = request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise errors.SessionInvalid()
    token = auth[7:].strip()
    return token


def get_session_object(request: Request, sm: SessionManager) -> "Session":
    from ..services.session_manager import Session

    token = get_session(request)
    session = sm.get_by_token(token)
    if session is None:
        raise errors.SessionInvalid()
    return session


def require_session(request: Request) -> "Session":
    """SEC: validate the Bearer token against an actual live session.

    Used by every protected route. A token that is merely ``Bearer <x>`` but
    does not correspond to a real, non-expired session is rejected with 401.
    """
    from ..app_context import AppContext
    from ..services.session_manager import Session

    token = get_session(request)
    ctx: AppContext = request.app.state.ctx
    session = ctx.sessions.get_by_token(token)
    if session is None:
        raise errors.SessionInvalid()
    return session
