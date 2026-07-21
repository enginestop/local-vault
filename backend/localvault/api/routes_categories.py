from typing import Literal

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import errors
from ..api.deps import get_user_id, require_session
from ..app_context import AppContext
from ..domain.models import Category, VaultPayload, nfkc_casefold, now_utc

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryBody(RequestModel):
    name: str


class TagBody(RequestModel):
    name: str


class TagRename(RequestModel):
    source: str
    target: str


def _require_unlocked(ctx: AppContext, user_id: str) -> None:
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()


def _check_if_match(request: Request, current_revision: int) -> None:
    value = request.headers.get("if-match")
    if value is None:
        raise errors.PreconditionRequired()
    expected = f'"{current_revision}"'
    if value.strip() != expected:
        raise errors.RevisionConflict(current_revision)


@router.get("/categories")
async def list_categories(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    return {
        "items": [item.model_dump(mode="json") for item in ctx.vault.get_plaintext(user_id).categories],
        "vault_revision": await ctx.vault.get_current_revision(user_id),
    }


@router.post("/categories", status_code=201)
async def create_category(request: Request, body: CategoryBody) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    new_category = Category(name=body.name)

    def apply(payload: VaultPayload) -> VaultPayload:
        _ensure_unique_category(payload, new_category.name)
        payload.categories.append(new_category)
        return payload

    payload, _ = await ctx.vault.mutate(user_id, apply, event_type="category.changed", entity_type="category", entity_id=new_category.id, entity_revision=1)
    return next(item.model_dump(mode="json") for item in payload.categories if item.id == new_category.id)


@router.put("/categories/{category_id}")
async def rename_category(request: Request, category_id: str, body: CategoryBody) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    current = _find_category(ctx.vault.get_plaintext(user_id), category_id)
    _check_if_match(request, current.revision)

    def apply(payload: VaultPayload) -> VaultPayload:
        _ensure_unique_category(payload, body.name, exclude_id=category_id)
        target = _find_category(payload, category_id)
        replacement = Category.model_validate({**target.model_dump(mode="python"), "name": body.name, "updated_at": now_utc(), "revision": target.revision + 1})
        payload.categories = [replacement if item.id == category_id else item for item in payload.categories]
        return payload

    payload, _ = await ctx.vault.mutate(user_id, apply, event_type="category.changed", entity_type="category", entity_id=category_id, entity_revision=current.revision + 1)
    return next(item.model_dump(mode="json") for item in payload.categories if item.id == category_id)


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(request: Request, category_id: str):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    current = _find_category(ctx.vault.get_plaintext(user_id), category_id)
    _check_if_match(request, current.revision)

    def apply(payload: VaultPayload) -> VaultPayload:
        payload.categories = [item for item in payload.categories if item.id != category_id]
        for credential in payload.credentials:
            if credential.category_id == category_id:
                credential.category_id = None
                credential.updated_at = now_utc()
                credential.revision += 1
        return payload

    await ctx.vault.mutate(user_id, apply, pre_operation="delete_category", event_type="category.changed", entity_type="category", entity_id=category_id, entity_revision=current.revision)
    return None


@router.get("/tags")
async def list_tags(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    tags = list(ctx.vault.get_plaintext(user_id).tags)
    known = {nfkc_casefold(tag) for tag in tags}
    for credential in ctx.vault.get_plaintext(user_id).credentials:
        for tag in credential.tags:
            if nfkc_casefold(tag) not in known:
                tags.append(tag)
                known.add(nfkc_casefold(tag))
    return {"items": sorted(tags, key=nfkc_casefold), "vault_revision": await ctx.vault.get_current_revision(user_id)}


@router.post("/tags", status_code=201)
async def create_tag(request: Request, body: TagBody) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    name = _clean_tag(body.name)
    if any(nfkc_casefold(tag) == nfkc_casefold(name) for tag in ctx.vault.get_plaintext(user_id).tags):
        raise errors.ConflictError("TAG_EXISTS", "Tag already exists")

    def apply(payload: VaultPayload) -> VaultPayload:
        payload.tags.append(name)
        return payload

    await ctx.vault.mutate(user_id, apply, event_type="tag.changed", entity_type="tag")
    return {"name": name}


@router.post("/tags/rename")
async def rename_tag(request: Request, body: TagRename, x_vault_revision: int | None = Header(default=None)) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    await _check_vault_revision(ctx, user_id, x_vault_revision)
    source = _clean_tag(body.source)
    target = _clean_tag(body.target)
    if not _tag_exists(ctx.vault.get_plaintext(user_id), source):
        raise errors.NotFoundError("tag not found")

    def apply(payload: VaultPayload) -> VaultPayload:
        target_display = next((tag for tag in payload.tags if nfkc_casefold(tag) == nfkc_casefold(target)), target)
        payload.tags = _dedupe_tags([target_display if nfkc_casefold(tag) == nfkc_casefold(source) else tag for tag in payload.tags])
        for credential in payload.credentials:
            updated = _dedupe_tags([target_display if nfkc_casefold(tag) == nfkc_casefold(source) else tag for tag in credential.tags])
            if updated != credential.tags:
                credential.tags = updated
                credential.updated_at = now_utc()
                credential.revision += 1
        return payload

    _, revision = await ctx.vault.mutate(user_id, apply, pre_operation="rename_tag", event_type="tag.changed", entity_type="tag")
    return {"renamed": True, "vault_revision": revision}


@router.delete("/tags/{name}", status_code=204)
async def delete_tag(request: Request, name: str, x_vault_revision: int | None = Header(default=None)):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    await _check_vault_revision(ctx, user_id, x_vault_revision)
    if not _tag_exists(ctx.vault.get_plaintext(user_id), name):
        raise errors.NotFoundError("tag not found")

    def apply(payload: VaultPayload) -> VaultPayload:
        payload.tags = [tag for tag in payload.tags if nfkc_casefold(tag) != nfkc_casefold(name)]
        for credential in payload.credentials:
            updated = [tag for tag in credential.tags if nfkc_casefold(tag) != nfkc_casefold(name)]
            if updated != credential.tags:
                credential.tags = updated
                credential.updated_at = now_utc()
                credential.revision += 1
        return payload

    await ctx.vault.mutate(user_id, apply, pre_operation="delete_tag", event_type="tag.changed", entity_type="tag")
    return None


async def _check_vault_revision(ctx: AppContext, user_id: str, supplied: int | None) -> None:
    if supplied is None:
        raise errors.PreconditionRequired("X-Vault-Revision header required")
    current = await ctx.vault.get_current_revision(user_id)
    if supplied != current:
        raise errors.RevisionConflict(current)


def _find_category(payload: VaultPayload, category_id: str) -> Category:
    for category in payload.categories:
        if category.id == category_id:
            return category
    raise errors.NotFoundError("category not found")


def _ensure_unique_category(payload: VaultPayload, name: str, exclude_id: str | None = None) -> None:
    candidate = Category(name=name)
    if any(category.id != exclude_id and nfkc_casefold(category.name) == nfkc_casefold(candidate.name) for category in payload.categories):
        raise errors.ConflictError("CATEGORY_EXISTS", "Category already exists")


def _clean_tag(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 100:
        raise errors.ValidationError("tag name must be 1-100 characters")
    return cleaned


def _tag_exists(payload: VaultPayload, name: str) -> bool:
    key = nfkc_casefold(name)
    return any(nfkc_casefold(tag) == key for tag in payload.tags) or any(
        any(nfkc_casefold(tag) == key for tag in credential.tags) for credential in payload.credentials
    )


def _dedupe_tags(tags: list[str]) -> list[str]:
    result = []
    seen = set()
    for tag in tags:
        key = nfkc_casefold(tag)
        if key not in seen:
            result.append(tag)
            seen.add(key)
    return result
