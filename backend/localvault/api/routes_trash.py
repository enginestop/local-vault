from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..app_context import AppContext
from .. import errors
from ..api.deps import require_session
from ..domain.envelope import VaultEnvelope
from ..domain.models import now_utc

router = APIRouter()


@router.get("/trash")
async def list_trash(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()
    payload = ctx.vault.plaintext
    trashed = [c for c in payload.credentials if c.deleted_at is not None]
    items = sorted(trashed, key=lambda c: c.deleted_at or "", reverse=True)
    return {
        "items": [c.model_dump(mode="json") for c in items],
        "total": len(items),
        "vault_revision": ctx.vault.get_current_revision(),
    }


class EmptyTrashRequest(BaseModel):
    confirmation: bool = False
    count_expected: int = 0


@router.post("/trash/empty")
async def empty_trash(request: Request, body: EmptyTrashRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()
    payload = ctx.vault.plaintext
    trashed = [c for c in payload.credentials if c.deleted_at is not None]
    if len(trashed) != body.count_expected:
        raise errors.ConflictError("COUNT_STALE", f"Expected {body.count_expected} but {len(trashed)} trashed items exist")
    if not body.confirmation:
        raise errors.ValidationError("confirmation required")

    def fn(p):
        p.credentials = [c for c in p.credentials if c.deleted_at is None]
        return p

    await ctx.vault.mutate(fn, pre_operation="empty_trash")
    return {"emptied": True}


def _current_env(ctx):
    row = ctx.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
    return VaultEnvelope.from_row(dict(row))
