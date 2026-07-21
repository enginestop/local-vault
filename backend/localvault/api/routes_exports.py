from typing import Literal, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import errors
from ..api.deps import get_user_id, require_session
from ..api.routes_credentials import filter_credentials
from ..app_context import AppContext
from ..domain.envelope import VaultEnvelope
from ..services import export_service as exp
from ..crypto.aes import aes_gcm_decrypt
from ..crypto.kdf import derive_kek

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportFilter(RequestModel):
    q: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    favorite_only: bool = False
    status: Literal["active", "trash", "all"] = "active"
    has_url: bool = False
    has_username: bool = False
    tag_mode: Literal["and", "or"] = "and"
    sort_field: Literal["name", "created_at", "updated_at", "category", "favorite"] = "name"
    sort_direction: Literal["asc", "desc"] = "asc"


class ExportRequest(RequestModel):
    master_password: str
    profile: Literal["spreadsheet", "chromium", "firefox"] = "spreadsheet"
    scope: Literal["all", "filtered", "selected"] = "all"
    filter: ExportFilter = Field(default_factory=ExportFilter)
    selected_ids: list[str] = Field(default_factory=list)


async def _verify_master(ctx: AppContext, user_id: str, master_password: str) -> None:
    row = await ctx.vault._fetch_envelope(user_id)
    if row is None:
        raise errors.NotFoundError("vault envelope not found")
    env = VaultEnvelope.from_row(row)
    try:
        aad = f"LocalVault|master-wrap|1|{env.vault_id}|{env.schema_version}".encode()
        kek = derive_kek(master_password, env.kdf_salt)
        aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, aad)
    except Exception as exc:
        raise errors.ReauthRequired() from exc


@router.post("/exports")
async def export_vault(request: Request, body: ExportRequest):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    require_session(request)
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()
    await _verify_master(ctx, user_id, body.master_password)
    payload = ctx.vault.get_plaintext(user_id)
    if body.scope == "all":
        credentials = filter_credentials(payload, status="active")
    elif body.scope == "selected":
        selected = set(body.selected_ids)
        credentials = [c for c in payload.credentials if c.id in selected]
    else:
        credentials = filter_credentials(
            payload, q=body.filter.q, category=body.filter.category,
            tags=body.filter.tags, favorite_only=body.filter.favorite_only,
            status=body.filter.status, has_url=body.filter.has_url,
            has_username=body.filter.has_username, tag_mode=body.filter.tag_mode,
            sort_field=body.filter.sort_field, sort_direction=body.filter.sort_direction,
        )
    selected_payload = payload.model_copy(deep=True)
    selected_payload.credentials = credentials
    if body.profile == "spreadsheet":
        content = exp.build_spreadsheet(selected_payload)[0]
        data = content.encode("utf-8-sig")
    elif body.profile == "chromium":
        data = exp.build_chromium(selected_payload).encode("utf-8")
    else:
        data = exp.build_firefox(selected_payload).encode("utf-8")
    filename = f"localvault-{body.profile}-{_stamp()}.csv"
    return StreamingResponse(
        iter([data]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
