import os
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from .. import errors
from ..api.deps import require_session
from ..app_context import AppContext
from ..crypto.aes import aes_gcm_decrypt
from ..crypto.kdf import derive_kek
from ..crypto.recovery import decode_recovery_seed, derive_recovery_kek
from ..domain.envelope import (
    FORMAT_VERSION,
    KDF_ALGORITHM,
    SCHEMA_VERSION,
    VaultEnvelope,
)
from ..domain.models import VaultPayload, validate_payload_size

router = APIRouter()


def _require_unlocked(ctx: AppContext, request: Request) -> None:
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()


@router.get("/backups")
async def list_backups(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    return {
        "items": ctx.backups.list_manifests(),
        "vault_revision": ctx.vault.get_current_revision(),
    }


@router.post("/backups/manual")
async def manual_backup(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    env = _current_env(ctx)
    try:
        with ctx.backups.transaction() as backup_tx:
            backup_id = backup_tx.write_backup(env, kind="manual")
    except Exception as exc:
        raise errors.StorageError("manual backup failed") from exc
    ctx.backups.apply_retention()
    manifest = next(
        item
        for item in ctx.backups.list_manifests()
        if item["backup_id"] == backup_id
    )
    return manifest


@router.get("/backups/{backup_id}/download")
async def download_backup(request: Request, backup_id: str):
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    path = ctx.backups.get_path(backup_id)
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
    _require_unlocked(ctx, request)
    if file is not None:
        content = await file.read()
        manifest, env = ctx.backups.parse_upload(content)
    elif backup_id:
        manifest, env = ctx.backups.read_backup(backup_id)
    else:
        raise errors.ValidationError("backup_id or file required")
    _validate_envelope_metadata(env)
    dek = _candidate_dek(ctx, env, master_password, recovery_key)
    try:
        plaintext = aes_gcm_decrypt(
            dek,
            env.payload_nonce,
            env.payload_ciphertext,
            _payload_aad(env),
        )
        payload = VaultPayload.model_validate_json(plaintext)
        validate_payload_size(payload)
    except errors.ProblemError:
        raise
    except Exception as exc:
        raise errors.ValidationError("backup payload is invalid") from exc

    current = _current_env(ctx)
    try:
        with ctx.backups.transaction() as backup_tx:
            backup_tx.write_backup(
                current, kind="pre_operation", operation="restore"
            )
            ctx.vault._write_envelope(backup_tx.tx, env)
    except Exception as exc:
        raise errors.StorageError("restore failed") from exc
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return {
        "restored": True,
        "vault_revision": env.vault_revision,
        "backup_id": manifest.backup_id,
    }


def _candidate_dek(
    ctx: AppContext,
    env: VaultEnvelope,
    master_password: Optional[str],
    recovery_key: Optional[str],
) -> bytes:
    if ctx.vault.is_unlocked() and ctx.vault.vault_id == env.vault_id:
        dek = ctx.vault._dek
        if dek is not None:
            return dek
    if recovery_key and env.recovery_wrap_nonce and env.wrapped_dek_recovery:
        try:
            seed = decode_recovery_seed(recovery_key)
            recovery_kek = derive_recovery_kek(seed, env.vault_id)
            return aes_gcm_decrypt(
                recovery_kek,
                env.recovery_wrap_nonce,
                env.wrapped_dek_recovery,
                _recovery_aad(env),
            )
        except Exception:
            pass
    if master_password:
        try:
            kek = derive_kek(master_password, env.kdf_salt)
            return aes_gcm_decrypt(
                kek,
                env.master_wrap_nonce,
                env.wrapped_dek_master,
                _master_aad(env),
            )
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


def _current_env(ctx: AppContext) -> VaultEnvelope:
    row = ctx.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
    if row is None:
        raise errors.NotFoundError("vault envelope not found")
    return VaultEnvelope.from_row(dict(row))


def _master_aad(env: VaultEnvelope) -> bytes:
    return (
        f"LocalVault|master-wrap|1|{env.vault_id}|{env.schema_version}"
    ).encode()


def _recovery_aad(env: VaultEnvelope) -> bytes:
    return (
        f"LocalVault|recovery-wrap|1|{env.vault_id}|{env.schema_version}"
    ).encode()


def _payload_aad(env: VaultEnvelope) -> bytes:
    return (
        f"LocalVault|payload|1|{env.vault_id}|{env.schema_version}|"
        f"{env.vault_revision}"
    ).encode()
