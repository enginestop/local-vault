from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..app_context import AppContext
from .. import errors
from ..api.deps import get_user_id, require_session
from ..domain.envelope import VaultEnvelope
from ..domain.models import now_utc

router = APIRouter()


@router.get("/trash")
async def list_trash(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()
    payload = ctx.vault.get_plaintext(user_id)
    trashed = [c for c in payload.credentials if c.deleted_at is not None]
    items = sorted(trashed, key=lambda c: c.deleted_at or "", reverse=True)
    return {
        "items": [c.model_dump(mode="json") for c in items],
        "total": len(items),
        "vault_revision": await ctx.vault.get_current_revision(user_id),
    }


class EmptyTrashRequest(BaseModel):
    confirmation: bool = False
    count_expected: int = 0


@router.post("/trash/empty")
async def empty_trash(request: Request, body: EmptyTrashRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()
    payload = ctx.vault.get_plaintext(user_id)
    trashed = [c for c in payload.credentials if c.deleted_at is not None]
    if len(trashed) != body.count_expected:
        raise errors.ConflictError("COUNT_STALE", f"Expected {body.count_expected} but {len(trashed)} trashed items exist")
    if not body.confirmation:
        raise errors.ValidationError("confirmation required")

    def fn(p):
        p.credentials = [c for c in p.credentials if c.deleted_at is None]
        return p

    await ctx.vault.mutate(user_id, fn, pre_operation="empty_trash")
    return {"emptied": True}
