import os
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import errors
from ..api.deps import get_user_id, require_session
from ..app_context import AppContext
from ..crypto.aes import aes_gcm_decrypt
from ..crypto.kdf import derive_kek
from ..crypto.recovery import decode_recovery_seed, derive_recovery_kek
from ..domain.envelope import FORMAT_VERSION, KDF_ALGORITHM, SCHEMA_VERSION, VaultEnvelope
from ..domain.models import VaultPayload, validate_payload_size

router = APIRouter()


def _require_unlocked(ctx: AppContext, user_id: str) -> None:
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()


@router.get("/backups")
async def list_backups(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    return {
        "items": await ctx.backups.list_manifests(user_id),
        "vault_revision": await ctx.vault.get_current_revision(user_id),
    }


@router.post("/backups/manual")
async def manual_backup(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    env = await _current_env(ctx, user_id)
    try:
        backup_id = await ctx.backups.write_backup(user_id, env, kind="manual")
    except Exception as exc:
        raise errors.StorageError("manual backup failed") from exc
    await ctx.backups.apply_retention(user_id)
    manifests = await ctx.backups.list_manifests(user_id)
    return next(item for item in manifests if item["backup_id"] == backup_id)


@router.get("/backups/{backup_id}/download")
async def download_backup(request: Request, backup_id: str):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    path = await ctx.backups.get_path(backup_id, user_id)
    return FileResponse(
        path,
        filename=os.path.basename(path),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/backups/restore")
async def restore_backup(
    request: Request,
    backup_id: Optional[str] = Form(None),
    master_password: Optional[str] = Form(None),
    recovery_key: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(default=None),
):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    if file is not None:
        content = await file.read()
        manifest, env = ctx.backups.parse_upload(content)
    elif backup_id:
        manifest, env = await ctx.backups.read_backup(backup_id, user_id)
    else:
        raise errors.ValidationError("backup_id or file required")
    _validate_envelope_metadata(env)
    dek = _candidate_dek(ctx, user_id, env, master_password, recovery_key)
    try:
        plaintext = aes_gcm_decrypt(dek, env.payload_nonce, env.payload_ciphertext, _payload_aad(env))
        payload = VaultPayload.model_validate_json(plaintext)
        validate_payload_size(payload)
    except errors.ProblemError:
        raise
    except Exception as exc:
        raise errors.ValidationError("backup payload is invalid") from exc

    cur_env = await _current_env(ctx, user_id)
    try:
        await ctx.backups.write_backup(user_id, cur_env, kind="pre_operation", operation="restore")
        await ctx.vault._write_envelope(user_id, env)
    except Exception as exc:
        raise errors.StorageError("restore failed") from exc
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return {"restored": True, "vault_revision": env.vault_revision, "backup_id": manifest.backup_id}


async def _current_env(ctx: AppContext, user_id: str) -> VaultEnvelope:
    row = await ctx.vault._fetch_envelope(user_id)
    if row is None:
        raise errors.NotFoundError("vault envelope not found")
    return VaultEnvelope.from_row(row)


def _candidate_dek(ctx: AppContext, user_id: str, env: VaultEnvelope, master_password: Optional[str], recovery_key: Optional[str]) -> bytes:
    if ctx.vault.is_unlocked(user_id) and ctx.vault.get_vault_id(user_id) == env.vault_id:
        dek = ctx.vault.get_dek(user_id)
        if dek is not None:
            return dek
    if recovery_key and env.recovery_wrap_nonce and env.wrapped_dek_recovery:
        try:
            seed = decode_recovery_seed(recovery_key)
            recovery_kek = derive_recovery_kek(seed, env.vault_id)
            return aes_gcm_decrypt(recovery_kek, env.recovery_wrap_nonce, env.wrapped_dek_recovery, _recovery_aad(env))
        except Exception:
            pass
    if master_password:
        try:
            kek = derive_kek(master_password, env.kdf_salt)
            return aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
        except Exception:
            pass
    raise errors.ReauthRequired()


def _validate_envelope_metadata(env: VaultEnvelope) -> None:
    if env.schema_version > SCHEMA_VERSION:
        raise errors.ValidationError("backup schema is newer than this application")
    if env.schema_version != SCHEMA_VERSION:
        raise errors.ValidationError("unsupported backup schema")
    if env.format_version != FORMAT_VERSION or env.kdf_algorithm != KDF_ALGORITHM:
        raise errors.ValidationError("unsupported backup encryption format")


def _master_aad(env: VaultEnvelope) -> bytes:
    return f"LocalVault|master-wrap|1|{env.vault_id}|{env.schema_version}".encode()


def _recovery_aad(env: VaultEnvelope) -> bytes:
    return f"LocalVault|recovery-wrap|1|{env.vault_id}|{env.schema_version}".encode()


def _payload_aad(env: VaultEnvelope) -> bytes:
    return f"LocalVault|payload|1|{env.vault_id}|{env.schema_version}|{env.vault_revision}".encode()
