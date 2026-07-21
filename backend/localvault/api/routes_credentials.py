from typing import Literal, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import errors
from ..api.deps import require_session
from ..app_context import AppContext
from ..domain.models import (
    Category,
    Credential,
    CustomField,
    PasswordHistoryEntry,
    VaultPayload,
    nfkc_casefold,
    now_utc,
)

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_unlocked(ctx: AppContext, request: Request) -> None:
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()


def _parse_if_match(request: Request) -> int:
    if_match = request.headers.get("if-match")
    if if_match is None:
        raise errors.PreconditionRequired()
    value = if_match.strip()
    if len(value) < 3 or not value.startswith('"') or not value.endswith('"') or not value[1:-1].isdigit():
        raise errors.ValidationError('If-Match must be a quoted integer revision')
    return int(value[1:-1])


def _check_if_match(request: Request, current_rev: int) -> None:
    if _parse_if_match(request) != current_rev:
        raise errors.RevisionConflict(current_rev)


class CredentialCreate(RequestModel):
    name: str
    url: Optional[str] = None
    username: Optional[str] = None
    password: str = ""
    category_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    favorite: bool = False
    notes: str = ""
    custom_fields: list[CustomField] = Field(default_factory=list)


class CredentialUpdate(RequestModel):
    name: str
    url: Optional[str]
    username: Optional[str]
    password: str
    category_id: Optional[str]
    tags: list[str]
    favorite: bool
    notes: str
    custom_fields: list[CustomField]
    base_revision: int = Field(ge=1)
    conflict_resolution: Optional[Literal["overwrite"]] = None


def serialize_credential(credential: Credential) -> dict:
    return credential.model_dump(mode="json")


def filter_credentials(
    payload: VaultPayload,
    *,
    q: str = "",
    category: str = "",
    tags: list[str] | None = None,
    favorite_only: bool = False,
    status: Literal["active", "trash", "all"] = "active",
    has_url: bool = False,
    has_username: bool = False,
    tag_mode: Literal["and", "or"] = "and",
    sort_field: Literal["name", "created_at", "updated_at", "category", "favorite"] = "name",
    sort_direction: Literal["asc", "desc"] = "asc",
) -> list[Credential]:
    items = list(payload.credentials)
    if status == "active":
        items = [item for item in items if item.deleted_at is None]
    elif status == "trash":
        items = [item for item in items if item.deleted_at is not None]
    if q:
        needle = nfkc_casefold(q)
        items = [item for item in items if _matches_query(payload, item, needle)]
    if category:
        items = [
            item
            for item in items
            if _category_matches(payload, item.category_id, category)
        ]
    wanted_tags = [nfkc_casefold(tag) for tag in (tags or []) if tag.strip()]
    if wanted_tags:
        def matches_tags(item: Credential) -> bool:
            owned = {nfkc_casefold(tag) for tag in item.tags}
            predicate = all if tag_mode == "and" else any
            return predicate(tag in owned for tag in wanted_tags)

        items = [item for item in items if matches_tags(item)]
    if favorite_only:
        items = [item for item in items if item.favorite]
    if has_url:
        items = [item for item in items if item.url]
    if has_username:
        items = [item for item in items if item.username]
    return _sort(items, sort_field, sort_direction, payload)


@router.get("/credentials")
async def list_credentials(
    request: Request,
    q: str = "",
    category: str = "",
    tag: list[str] = Query(default=[]),
    favorite_only: bool = False,
    status: Literal["active", "trash", "all"] = "active",
    has_url: bool = False,
    has_username: bool = False,
    tag_mode: Literal["and", "or"] = "and",
    sort_field: Literal["name", "created_at", "updated_at", "category", "favorite"] = "name",
    sort_direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    items = filter_credentials(
        ctx.vault.plaintext,
        q=q,
        category=category,
        tags=tag,
        favorite_only=favorite_only,
        status=status,
        has_url=has_url,
        has_username=has_username,
        tag_mode=tag_mode,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": [serialize_credential(item) for item in items[start : start + page_size]],
        "page": page,
        "page_size": page_size,
        "total": total,
        "vault_revision": ctx.vault.get_current_revision(),
    }


@router.post("/credentials", status_code=201)
async def create_credential(request: Request, body: CredentialCreate) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    new_credential = Credential.model_validate(body.model_dump())

    def apply(payload: VaultPayload) -> VaultPayload:
        _validate_category(payload, new_credential.category_id)
        payload.credentials.append(new_credential)
        _merge_catalog_tags(payload, new_credential.tags)
        return payload

    payload, _ = await ctx.vault.mutate(
        apply,
        event_type="credential.created",
        entity_type="credential",
        entity_id=new_credential.id,
        entity_revision=1,
    )
    return serialize_credential(
        next(item for item in payload.credentials if item.id == new_credential.id)
    )


@router.get("/credentials/{cred_id}")
async def get_credential(request: Request, cred_id: str) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    return serialize_credential(_find(ctx, cred_id))


@router.put("/credentials/{cred_id}")
async def update_credential(
    request: Request, cred_id: str, body: CredentialUpdate
) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    current = _find(ctx, cred_id)
    matched_revision = _parse_if_match(request)
    if matched_revision != body.base_revision:
        raise errors.ValidationError("base_revision must match If-Match")
    if current.revision != body.base_revision and body.conflict_resolution != "overwrite":
        raise errors.EditConflict(current.revision, current.updated_at)
    changes = body.model_dump(exclude={"base_revision", "conflict_resolution"})

    def apply(payload: VaultPayload) -> VaultPayload:
        target = next(item for item in payload.credentials if item.id == cred_id)
        values = target.model_dump(mode="python")
        old_password = target.password
        values.update(changes)
        _validate_category(payload, changes["category_id"])
        if changes["password"] != old_password:
            history = list(target.password_history)
            history.insert(
                0,
                PasswordHistoryEntry(
                    password=old_password,
                    changed_at=now_utc(),
                ),
            )
            values["password_history"] = history[:5]
        values["updated_at"] = now_utc()
        values["revision"] = target.revision + 1
        replacement = Credential.model_validate(values)
        payload.credentials = [
            replacement if item.id == cred_id else item
            for item in payload.credentials
        ]
        _merge_catalog_tags(payload, replacement.tags)
        return payload

    payload, _ = await ctx.vault.mutate(
        apply,
        event_type="credential.updated",
        entity_type="credential",
        entity_id=cred_id,
        entity_revision=current.revision + 1,
    )
    return serialize_credential(
        next(item for item in payload.credentials if item.id == cred_id)
    )


@router.post("/credentials/{cred_id}/trash")
async def trash_credential(request: Request, cred_id: str) -> dict:
    return await _set_trash_state(request, cred_id, True)


@router.post("/credentials/{cred_id}/restore")
async def restore_credential(request: Request, cred_id: str) -> dict:
    return await _set_trash_state(request, cred_id, False)


async def _set_trash_state(request: Request, cred_id: str, trashed: bool) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    current = _find(ctx, cred_id)
    _check_if_match(request, current.revision)

    def apply(payload: VaultPayload) -> VaultPayload:
        target = next(item for item in payload.credentials if item.id == cred_id)
        target.deleted_at = now_utc() if trashed else None
        target.updated_at = now_utc()
        target.revision += 1
        return payload

    await ctx.vault.mutate(
        apply,
        pre_operation="trash" if trashed else None,
        event_type="credential.trashed" if trashed else "credential.restored",
        entity_type="credential",
        entity_id=cred_id,
        entity_revision=current.revision + 1,
    )
    return {"trashed" if trashed else "restored": True}


@router.delete("/credentials/{cred_id}", status_code=204)
async def purge_credential(request: Request, cred_id: str):
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    current = _find(ctx, cred_id)
    if current.deleted_at is None:
        raise errors.ProblemError(
            "NOT_TRASHED", "Not trashed", "Only trashed items can be purged", 400
        )
    _check_if_match(request, current.revision)

    def apply(payload: VaultPayload) -> VaultPayload:
        payload.credentials = [item for item in payload.credentials if item.id != cred_id]
        return payload

    await ctx.vault.mutate(
        apply,
        pre_operation="purge",
        event_type="credential.purged",
        entity_type="credential",
        entity_id=cred_id,
        entity_revision=current.revision,
    )
    return None


BulkAction = Literal[
    "trash",
    "restore",
    "purge",
    "set_favorite",
    "unset_favorite",
    "add_tags",
    "remove_tags",
    "set_category",
]


class BulkTarget(RequestModel):
    id: str
    revision: int = Field(ge=1)


class BulkArguments(RequestModel):
    favorite: Optional[bool] = None
    tags: list[str] = Field(default_factory=list)
    category_id: Optional[str] = None


class BulkRequest(RequestModel):
    action: BulkAction
    ids: list[BulkTarget] = Field(min_length=1)
    arguments: BulkArguments = Field(default_factory=BulkArguments)


@router.post("/credentials/bulk")
async def bulk_credentials(request: Request, body: BulkRequest) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    by_id = {item.id: item for item in ctx.vault.plaintext.credentials}
    conflicts = []
    for target in body.ids:
        current = by_id.get(target.id)
        if current is None or current.revision != target.revision:
            conflicts.append(
                {
                    "id": target.id,
                    "current_revision": current.revision if current else None,
                }
            )
        elif body.action == "purge" and current.deleted_at is None:
            conflicts.append({"id": target.id, "reason": "NOT_TRASHED"})
    if conflicts:
        raise errors.ProblemError(
            "BULK_CONFLICT",
            "Bulk operation conflict",
            "One or more items are missing, stale, or invalid for this action.",
            409,
            conflicts,
        )
    if body.action == "set_category":
        _validate_category(ctx.vault.plaintext, body.arguments.category_id)
    target_ids = {item.id for item in body.ids}
    changed_ids = {
        item.id
        for item in by_id.values()
        if item.id in target_ids and _bulk_would_change(item, body)
    }
    if not changed_ids:
        return {
            "applied": True,
            "count": 0,
            "vault_revision": ctx.vault.get_current_revision(),
        }

    def apply(payload: VaultPayload) -> VaultPayload:
        if body.action == "purge":
            payload.credentials = [
                item for item in payload.credentials if item.id not in changed_ids
            ]
            return payload
        for target in payload.credentials:
            if target.id not in changed_ids:
                continue
            if body.action == "trash":
                target.deleted_at = now_utc()
            elif body.action == "restore":
                target.deleted_at = None
            elif body.action in ("set_favorite", "unset_favorite"):
                target.favorite = body.action == "set_favorite"
            elif body.action == "add_tags":
                existing = {nfkc_casefold(tag) for tag in target.tags}
                target.tags.extend(
                    tag
                    for tag in body.arguments.tags
                    if nfkc_casefold(tag) not in existing
                )
            elif body.action == "remove_tags":
                removed = {nfkc_casefold(tag) for tag in body.arguments.tags}
                target.tags = [
                    tag for tag in target.tags if nfkc_casefold(tag) not in removed
                ]
            elif body.action == "set_category":
                target.category_id = body.arguments.category_id
            target.updated_at = now_utc()
            target.revision += 1
        if body.action == "add_tags":
            _merge_catalog_tags(payload, body.arguments.tags)
        return payload

    _, vault_revision = await ctx.vault.mutate(
        apply,
        pre_operation=f"bulk_{body.action}"
        if body.action in ("trash", "purge")
        else None,
    )
    return {
        "applied": True,
        "count": len(changed_ids),
        "vault_revision": vault_revision,
    }


def _bulk_would_change(item: Credential, body: BulkRequest) -> bool:
    if body.action == "trash":
        return item.deleted_at is None
    if body.action == "restore":
        return item.deleted_at is not None
    if body.action == "purge":
        return item.deleted_at is not None
    if body.action == "set_favorite":
        return not item.favorite
    if body.action == "unset_favorite":
        return item.favorite
    if body.action == "add_tags":
        existing = {nfkc_casefold(tag) for tag in item.tags}
        return any(nfkc_casefold(tag) not in existing for tag in body.arguments.tags)
    if body.action == "remove_tags":
        removed = {nfkc_casefold(tag) for tag in body.arguments.tags}
        return any(nfkc_casefold(tag) in removed for tag in item.tags)
    if body.action == "set_category":
        return item.category_id != body.arguments.category_id
    return False


def _matches_query(payload: VaultPayload, item: Credential, needle: str) -> bool:
    category_name = ""
    if item.category_id:
        category = next(
            (category for category in payload.categories if category.id == item.category_id),
            None,
        )
        category_name = category.name if category else ""
    values = [
        item.name,
        item.username or "",
        item.url or "",
        item.notes,
        category_name,
        *item.tags,
        *(field.label for field in item.custom_fields),
        *(field.value for field in item.custom_fields if field.type == "text"),
    ]
    return any(needle in nfkc_casefold(value) for value in values)


def _category_matches(payload: VaultPayload, category_id: Optional[str], value: str) -> bool:
    if not category_id:
        return False
    for category in payload.categories:
        if category.id == category_id:
            return category.id == value or nfkc_casefold(category.name) == nfkc_casefold(value)
    return False


def _sort(
    items: list[Credential],
    field: str,
    direction: str,
    payload: VaultPayload,
) -> list[Credential]:
    reverse = direction == "desc"

    def category_name(item: Credential) -> str:
        category = next(
            (cat for cat in payload.categories if cat.id == item.category_id), None
        )
        return nfkc_casefold(category.name) if category else ""

    key_functions = {
        "name": lambda item: nfkc_casefold(item.name),
        "created_at": lambda item: item.created_at,
        "updated_at": lambda item: item.updated_at,
        "category": category_name,
        "favorite": lambda item: item.favorite,
    }
    result = sorted(items, key=lambda item: item.id)
    return sorted(result, key=key_functions[field], reverse=reverse)


def _find(ctx: AppContext, credential_id: str) -> Credential:
    for credential in ctx.vault.plaintext.credentials:
        if credential.id == credential_id:
            return credential
    raise errors.NotFoundError("credential not found")


def _validate_category(payload: VaultPayload, category_id: Optional[str]) -> None:
    if category_id is not None and not any(
        category.id == category_id for category in payload.categories
    ):
        raise errors.ValidationError("category_id does not exist")


def _merge_catalog_tags(payload: VaultPayload, tags: list[str]) -> None:
    known = {nfkc_casefold(tag) for tag in payload.tags}
    for tag in tags:
        cleaned = tag.strip()
        if cleaned and nfkc_casefold(cleaned) not in known:
            payload.tags.append(cleaned)
            known.add(nfkc_casefold(cleaned))
