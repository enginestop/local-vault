import csv
import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import errors
from ..api.deps import require_session
from ..app_context import AppContext
from ..domain.models import (
    Category,
    Credential,
    CustomField,
    MAX_PAYLOAD_BYTES,
    PasswordHistoryEntry,
    VaultPayload,
    nfkc_casefold,
    now_utc,
)
from ..domain.normalize import norm_url, norm_username
from ..services import import_service as imp

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resolution(RequestModel):
    row_number: int = Field(ge=1)
    resolution: Literal["skip", "update", "keep_both"]


class PreviewUpdate(RequestModel):
    mapping: Optional[dict] = None
    resolutions: list[Resolution] = Field(default_factory=list)


def _require_unlocked(ctx: AppContext, request: Request):
    session = require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()
    return session


@router.post("/imports/previews")
async def create_preview(
    request: Request,
    file: UploadFile,
    profile: str = Form("auto"),
    delimiter: Optional[str] = Form(None),
    mapping: str = Form("{}"),
) -> dict:
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    content = await file.read(imp.MAX_UPLOAD_BYTES + 1)
    if len(content) > imp.MAX_UPLOAD_BYTES:
        raise errors.ValidationError("upload too large")
    try:
        sample = content[: 64 * 1024].decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise errors.ValidationError("encoding must be UTF-8") from exc
    selected_delimiter = delimiter or imp.detect_delimiter(sample)
    if selected_delimiter not in imp.DELIMITERS:
        raise errors.ValidationError("delimiter must be comma, semicolon, or tab")
    try:
        source_columns, source_rows = imp.parse_csv_document(
            content, selected_delimiter
        )
        mapping_value = json.loads(mapping) if mapping else {}
    except (UnicodeDecodeError, csv.Error, ValueError, json.JSONDecodeError) as exc:
        raise errors.ValidationError(f"invalid CSV or mapping: {exc}") from exc
    if len(source_rows) > imp.MAX_ROWS:
        raise errors.ValidationError("too many rows")
    resolved_profile = imp.detect_profile(source_columns) if profile == "auto" else profile
    if resolved_profile not in ("generic", "chromium", "firefox", "localvault"):
        raise errors.ValidationError("unknown import profile")
    resolved_mapping = mapping_value or imp.preset_columns(
        resolved_profile, source_columns
    )
    preview = imp.ImportPreview(
        id=str(uuid.uuid4()),
        session_id=session.session_id,
        base_vault_revision=ctx.vault.get_current_revision(),
        profile=resolved_profile,
        delimiter=selected_delimiter,
        mapping=resolved_mapping,
        source_columns=source_columns,
        source_rows=source_rows,
    )
    _rebuild_preview(ctx.vault.plaintext, preview)
    await ctx.imports.put(preview)
    return _preview_summary(preview)


@router.get("/imports/previews/{preview_id}")
async def get_preview(request: Request, preview_id: str) -> dict:
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    async with _owned(ctx, preview_id, session.session_id) as preview:
        return _preview_summary(preview)


@router.put("/imports/previews/{preview_id}")
async def update_preview(
    request: Request, preview_id: str, body: PreviewUpdate
) -> dict:
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    async with _owned(ctx, preview_id, session.session_id) as preview:
        if body.mapping is not None:
            preview.mapping = body.mapping
            _rebuild_preview(ctx.vault.plaintext, preview)
        by_row = {item.row_number: item.resolution for item in body.resolutions}
        for row in preview.valid_rows:
            if row["row_number"] in by_row:
                row["resolution"] = by_row[row["row_number"]]
        return _preview_summary(preview)


@router.get("/imports/previews/{preview_id}/errors.csv")
async def errors_csv(request: Request, preview_id: str):
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    async with _owned(ctx, preview_id, session.session_id) as preview:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=",", lineterminator="\r\n")
        writer.writerow(["row_number", "error_code", "message"])
        for invalid in preview.invalid_rows:
            for error in invalid["errors"]:
                writer.writerow(
                    [invalid["row_number"], error["code"], error["message"]]
                )
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="localvault-import-errors.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/imports/previews/{preview_id}/commit")
async def commit_preview(request: Request, preview_id: str) -> dict:
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    async with _owned(
        ctx, preview_id, session.session_id, remove_on_success=True
    ) as preview:
        if preview.base_vault_revision != ctx.vault.get_current_revision():
            raise errors.ConflictError(
                "PREVIEW_STALE", "Vault changed since preview; create a new preview"
            )
        committed_rows: list[int] = []

        def apply(payload: VaultPayload) -> VaultPayload:
            for row in preview.valid_rows:
                resolution = row["resolution"]
                if resolution == "skip":
                    continue
                candidate = Credential.model_validate(row["candidate"])
                data = row["data"]
                existing = _find_duplicate(payload, candidate.url, candidate.username)
                if resolution == "update" and existing is not None:
                    _update_existing(payload, existing, candidate, data, preview.mapping)
                else:
                    candidate.id = str(uuid.uuid4())
                    candidate.category_id = _find_or_create_category(
                        payload, data.get("category")
                    )
                    payload.credentials.append(candidate)
                _merge_tags(payload, candidate.tags)
                committed_rows.append(row["row_number"])
            return payload

        if any(row["resolution"] != "skip" for row in preview.valid_rows):
            await ctx.vault.mutate(apply)
        return {"committed": len(committed_rows), "rows": committed_rows}


@router.delete("/imports/previews/{preview_id}", status_code=204)
async def cancel_preview(request: Request, preview_id: str):
    ctx: AppContext = request.app.state.ctx
    session = _require_unlocked(ctx, request)
    try:
        await ctx.imports.remove_owned(preview_id, session.session_id)
    except KeyError as exc:
        raise errors.NotFoundError("preview not found or expired") from exc
    except PermissionError as exc:
        raise errors.ProblemError(
            "PREVIEW_FORBIDDEN", "Forbidden", "Preview belongs to another session", 403
        ) from exc
    return None


@asynccontextmanager
async def _owned(
    ctx: AppContext,
    preview_id: str,
    session_id: str,
    *,
    remove_on_success: bool = False,
):
    try:
        async with ctx.imports.owned(
            preview_id, session_id, remove_on_success=remove_on_success
        ) as preview:
            yield preview
    except KeyError as exc:
        raise errors.NotFoundError("preview not found or expired") from exc
    except PermissionError as exc:
        raise errors.ProblemError(
            "PREVIEW_FORBIDDEN", "Forbidden", "Preview belongs to another session", 403
        ) from exc


def _rebuild_preview(payload: VaultPayload, preview: imp.ImportPreview) -> None:
    preview.valid_rows.clear()
    preview.invalid_rows.clear()
    preview.conflicts.clear()
    preview.warnings.clear()
    if preview.profile == "firefox" and "name" not in preview.mapping.values():
        preview.warnings.append("Firefox has no name column; a display name is synthesized")
    for index, source in enumerate(preview.source_rows, start=1):
        try:
            data = _map_row(source, preview.mapping, preview.profile)
            candidate = _candidate(data, preview.profile)
        except Exception as exc:
            preview.invalid_rows.append(
                {
                    "row_number": index,
                    "errors": [{"code": "VALIDATION_ERROR", "message": str(exc)}],
                }
            )
            continue
        existing = _find_duplicate(payload, candidate.url, candidate.username)
        conflict = None
        if existing is not None:
            conflict = {
                "row_number": index,
                "existing_credential_id": existing.id,
                "reason": "duplicate url+username",
            }
            preview.conflicts.append(conflict)
        preview.valid_rows.append(
            {
                "row_number": index,
                "data": data,
                "candidate": candidate.model_dump(mode="python"),
                "conflict": conflict,
                "resolution": "skip" if conflict else "keep_both",
            }
        )


def _map_row(source: dict, mapping: dict, profile: str) -> dict:
    data: dict = {}
    for source_column, target in mapping.items():
        if source_column not in source or target in (None, "", "ignore"):
            continue
        value = source[source_column]
        if isinstance(target, dict) and target.get("target") == "custom_field":
            data.setdefault("custom_fields", []).append(
                {
                    "label": target.get("label", ""),
                    "type": target.get("type", "text"),
                    "value": value,
                }
            )
        elif isinstance(target, str):
            data[target] = value
    if profile == "localvault":
        escaped = {
            field.strip()
            for field in str(source.get("_localvault_escape_map", "")).split(";")
            if field.strip()
        }
        for field in escaped:
            value = data.get(field)
            if isinstance(value, str) and value.startswith("'"):
                data[field] = value[1:]
    return data


def _candidate(data: dict, profile: str) -> Credential:
    if profile == "firefox" and not str(data.get("name", "")).strip():
        data["name"] = _firefox_name(data)
    custom_fields = list(data.get("custom_fields", []))
    if data.get("custom_fields_json"):
        parsed = json.loads(data["custom_fields_json"])
        if not isinstance(parsed, list):
            raise ValueError("custom_fields_json must be an array")
        custom_fields.extend(parsed)
    created_at = _source_timestamp(data.get("created_at")) or now_utc()
    updated_at = _source_timestamp(data.get("updated_at")) or created_at
    if profile == "firefox":
        firefox_time = _epoch_timestamp(data.get("timeCreated"))
        changed_time = _epoch_timestamp(data.get("timePasswordChanged"))
        created_at = firefox_time or created_at
        updated_at = changed_time or created_at
    candidate = Credential(
        name=str(data.get("name", "")).strip(),
        url=str(data.get("url", "")).strip() or None,
        username=str(data.get("username", "")).strip() or None,
        password=str(data.get("password", "")),
        tags=_split_tags(data.get("tags")),
        favorite=_parse_favorite(data.get("favorite")),
        notes=str(data.get("notes", "")),
        custom_fields=[CustomField.model_validate(field) for field in custom_fields],
        created_at=created_at,
        updated_at=updated_at,
    )
    if candidate.payload_bytes > MAX_PAYLOAD_BYTES:
        raise ValueError("credential payload is too large")
    return candidate


def _find_duplicate(
    payload: VaultPayload, url: Optional[str], username: Optional[str]
) -> Optional[Credential]:
    key = (norm_url(url), norm_username(username))
    if not key[0] and not key[1]:
        return None
    return next(
        (
            credential
            for credential in payload.credentials
            if credential.deleted_at is None
            and (norm_url(credential.url), norm_username(credential.username)) == key
        ),
        None,
    )


def _update_existing(
    payload: VaultPayload,
    existing: Credential,
    candidate: Credential,
    data: dict,
    mapping: dict,
) -> None:
    mapped = {
        value for value in mapping.values() if isinstance(value, str)
    }
    values = existing.model_dump(mode="python")
    field_map = {
        "name": candidate.name,
        "url": candidate.url,
        "username": candidate.username,
        "password": candidate.password,
        "tags": candidate.tags,
        "favorite": candidate.favorite,
        "notes": candidate.notes,
        "custom_fields_json": candidate.custom_fields,
    }
    for field, value in field_map.items():
        if field in mapped:
            target_field = "custom_fields" if field == "custom_fields_json" else field
            values[target_field] = value
    if any(isinstance(value, dict) for value in mapping.values()):
        values["custom_fields"] = candidate.custom_fields
    if "category" in mapped:
        values["category_id"] = _find_or_create_category(
            payload, data.get("category")
        )
    if "password" in mapped and candidate.password != existing.password:
        history = list(existing.password_history)
        history.insert(
            0,
            PasswordHistoryEntry(
                password=existing.password,
                changed_at=now_utc(),
            ),
        )
        values["password_history"] = history[:5]
    values["id"] = existing.id
    values["created_at"] = existing.created_at
    values["updated_at"] = now_utc()
    values["revision"] = existing.revision + 1
    replacement = Credential.model_validate(values)
    payload.credentials = [
        replacement if item.id == existing.id else item
        for item in payload.credentials
    ]


def _find_or_create_category(payload: VaultPayload, name) -> Optional[str]:
    cleaned = str(name or "").strip()
    if not cleaned:
        return None
    for category in payload.categories:
        if nfkc_casefold(category.name) == nfkc_casefold(cleaned):
            return category.id
    category = Category(name=cleaned)
    payload.categories.append(category)
    return category.id


def _merge_tags(payload: VaultPayload, tags: list[str]) -> None:
    known = {nfkc_casefold(tag) for tag in payload.tags}
    for tag in tags:
        if nfkc_casefold(tag) not in known:
            payload.tags.append(tag)
            known.add(nfkc_casefold(tag))


def _preview_summary(preview: imp.ImportPreview) -> dict:
    return {
        "id": preview.id,
        "profile": preview.profile,
        "delimiter": preview.delimiter,
        "mapping": preview.mapping,
        "source_columns": preview.source_columns,
        "base_vault_revision": preview.base_vault_revision,
        "valid_count": len(preview.valid_rows),
        "invalid_count": len(preview.invalid_rows),
        "conflict_count": len(preview.conflicts),
        "warnings": preview.warnings,
        "sample": [_redacted(row) for row in preview.valid_rows[:100]],
        "invalid_sample": preview.invalid_rows[:100],
        "conflicts": preview.conflicts,
    }


def _redacted(row: dict) -> dict:
    data = row["data"]
    return {
        "row_number": row["row_number"],
        "data": {
            field: data.get(field, "")
            for field in ("name", "url", "username", "category", "tags")
        },
        "conflict": row["conflict"],
        "resolution": row["resolution"],
    }


def _split_tags(value) -> list[str]:
    return [tag.strip() for tag in str(value or "").split(";") if tag.strip()]


def _parse_favorite(value) -> bool:
    if value in (None, ""):
        return False
    normalized = str(value).strip().lower()
    if normalized in ("true", "1", "yes", "ya"):
        return True
    if normalized in ("false", "0", "no", "tidak"):
        return False
    raise ValueError("favorite must be a supported boolean value")


def _source_timestamp(value) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        if parsed > datetime.now(timezone.utc):
            return None
        return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"
    except (TypeError, ValueError):
        return None


def _epoch_timestamp(value) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    if parsed > datetime.now(timezone.utc):
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


def _firefox_name(data: dict) -> str:
    url = str(data.get("url", "")).strip()
    if url:
        hostname = urlparse(url).hostname
        if hostname:
            return hostname
    username = str(data.get("username", "")).strip()
    return username or "Imported Firefox login"
