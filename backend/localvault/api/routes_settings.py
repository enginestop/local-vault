from fastapi import APIRouter, Request
from fastapi import Form
from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional

from ..app_context import AppContext
from .. import errors
from ..api.deps import require_session
from ..domain.envelope import VaultEnvelope
from ..domain.models import VaultSettings, nfkc_casefold
from ..domain.password_policy import validate_master_password, PasswordPolicyError
from ..crypto.kdf import derive_kek, new_salt, verify_kek
from ..crypto.aes import aes_gcm_encrypt, aes_gcm_decrypt
from ..crypto.recovery import derive_recovery_kek, new_recovery_seed, encode_recovery_key, decode_recovery_seed
from ..crypto.csprng import new_nonce

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_unlocked(ctx, request):
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()


def _current_env(ctx):
    row = ctx.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
    return VaultEnvelope.from_row(dict(row))


def _master_aad(env):
    return ("LocalVault|master-wrap|1|" + env.vault_id + "|" + str(env.schema_version)).encode()


def _rec_aad(env):
    return ("LocalVault|recovery-wrap|1|" + env.vault_id + "|" + str(env.schema_version)).encode()


def _payload_aad(env, rev):
    return ("LocalVault|payload|1|" + env.vault_id + "|" + str(env.schema_version) + "|" + str(rev)).encode()


@router.get("/settings/security")
async def security_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    env = _current_env(ctx)
    return {
        "kdf_algorithm": env.kdf_algorithm,
        "kdf_m_cost_kib": env.kdf_m_cost_kib,
        "kdf_t_cost": env.kdf_t_cost,
        "kdf_parallelism": env.kdf_parallelism,
        "recovery_enabled": env.recovery_wrap_nonce is not None,
    }


class MasterPasswordChange(RequestModel):
    current_master_password: str
    new_master_password: str
    confirm_new_master_password: str
    weak_password_acknowledged: bool = False


@router.put("/settings/security/master-password")
async def change_master(request: Request, body: MasterPasswordChange) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    if body.new_master_password != body.confirm_new_master_password:
        raise errors.ValidationError("confirmation mismatch")
    try:
        validate_master_password(
            body.new_master_password,
            body.confirm_new_master_password,
            body.weak_password_acknowledged,
        )
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    env = _current_env(ctx)
    # verify current
    try:
        kek = derive_kek(body.current_master_password, env.kdf_salt)
        dek = aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
    # BAK-014: rewrap DEK with new KEK (new salt), payload unchanged
    new_salt_v = new_salt()
    new_kek = derive_kek(body.new_master_password, new_salt_v)
    master_nonce = new_nonce()
    wrapped = aes_gcm_encrypt(new_kek, master_nonce, dek, _master_aad(env))
    # preserve recovery wrap
    new_env = VaultEnvelope(
        vault_id=env.vault_id, schema_version=env.schema_version, vault_revision=env.vault_revision,
        format_version=1, kdf_algorithm="argon2id", kdf_salt=new_salt_v,
        kdf_m_cost_kib=65536, kdf_t_cost=3, kdf_parallelism=1,
        master_wrap_nonce=master_nonce, wrapped_dek_master=wrapped,
        recovery_wrap_nonce=env.recovery_wrap_nonce, wrapped_dek_recovery=env.wrapped_dek_recovery,
        payload_nonce=env.payload_nonce, payload_ciphertext=env.payload_ciphertext,
        envelope_checksum=_checksum(env.vault_id, env.vault_revision, env.payload_ciphertext, wrapped),
    )
    with ctx.backups.transaction() as backup_tx:
        backup_tx.write_backup(
            env, kind="pre_operation", operation="master_password_change"
        )
        ctx.vault._write_envelope(backup_tx.tx, new_env)
    return {"changed": True}


class RecoveryKeyAction(RequestModel):
    action: Literal["enable", "rotate"]
    master_password: Optional[str] = None
    current_master_password: Optional[str] = None


@router.get("/settings/security/recovery-key")
async def recovery_key_status(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    if not ctx.vault.is_unlocked():
        raise errors.VaultLocked()
    env = _current_env(ctx)
    return {"recovery_key_present": env.recovery_wrap_nonce is not None}


@router.post("/settings/security/recovery-key")
async def recovery_action(request: Request, body: RecoveryKeyAction) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    env = _current_env(ctx)
    # need DEK (unlocked) and current master to rewrap recovery
    dek = ctx.vault._dek
    if dek is None:
        raise errors.VaultLocked()
    mp = body.current_master_password or body.master_password
    try:
        kek = derive_kek(mp, env.kdf_salt)
        aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
    rec_nonce = None
    wrapped_rec = None
    new_rec_key = None
    if body.action in ("enable", "rotate"):
        seed = new_recovery_seed()
        rec_kek = derive_recovery_kek(seed, env.vault_id)
        rec_nonce = new_nonce()
        wrapped_rec = aes_gcm_encrypt(rec_kek, rec_nonce, dek, _rec_aad(env))
        new_rec_key = encode_recovery_key(seed)
    new_env = VaultEnvelope(
        vault_id=env.vault_id, schema_version=env.schema_version, vault_revision=env.vault_revision,
        format_version=1, kdf_algorithm="argon2id", kdf_salt=env.kdf_salt,
        kdf_m_cost_kib=65536, kdf_t_cost=3, kdf_parallelism=1,
        master_wrap_nonce=env.master_wrap_nonce, wrapped_dek_master=env.wrapped_dek_master,
        recovery_wrap_nonce=rec_nonce, wrapped_dek_recovery=wrapped_rec,
        payload_nonce=env.payload_nonce, payload_ciphertext=env.payload_ciphertext,
        envelope_checksum=env.envelope_checksum,
    )
    with ctx.backups.transaction() as backup_tx:
        backup_tx.write_backup(
            env, kind="pre_operation", operation="recovery_" + body.action
        )
        ctx.vault._write_envelope(backup_tx.tx, new_env)
    return {"recovery_key": new_rec_key, "enabled": wrapped_rec is not None}


class RecoveryDisable(RequestModel):
    current_master_password: str


@router.delete("/settings/security/recovery-key", status_code=204)
async def recovery_disable(request: Request, body: RecoveryDisable):
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    env = _current_env(ctx)
    try:
        kek = derive_kek(body.current_master_password, env.kdf_salt)
        aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
    new_env = VaultEnvelope(
        vault_id=env.vault_id, schema_version=env.schema_version, vault_revision=env.vault_revision,
        format_version=1, kdf_algorithm="argon2id", kdf_salt=env.kdf_salt,
        kdf_m_cost_kib=65536, kdf_t_cost=3, kdf_parallelism=1,
        master_wrap_nonce=env.master_wrap_nonce, wrapped_dek_master=env.wrapped_dek_master,
        recovery_wrap_nonce=None, wrapped_dek_recovery=None,
        payload_nonce=env.payload_nonce, payload_ciphertext=env.payload_ciphertext,
        envelope_checksum=env.envelope_checksum,
    )
    with ctx.backups.transaction() as backup_tx:
        backup_tx.write_backup(
            env, kind="pre_operation", operation="recovery_disable"
        )
        ctx.vault._write_envelope(backup_tx.tx, new_env)
    return None


class ResetVault(RequestModel):
    master_password: str
    confirm_recovery_phrase: str
    new_master_password: str
    confirm_new_master_password: str
    weak_password_acknowledged: bool = False
    create_recovery_key: bool = False


@router.post("/settings/security/reset-vault")
async def reset_vault(request: Request, body: ResetVault) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    if body.confirm_recovery_phrase != "RESET LOCALVAULT":
        raise errors.ValidationError("confirmation phrase must be 'RESET LOCALVAULT'")
    try:
        validate_master_password(
            body.new_master_password,
            body.confirm_new_master_password,
            body.weak_password_acknowledged,
        )
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    env = _current_env(ctx)
    try:
        kek = derive_kek(body.master_password, env.kdf_salt)
        aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
    # new vault id/dek, empty payload
    import uuid

    vault_id = str(uuid.uuid4())
    dek = __import__("localvault.crypto.csprng", fromlist=["random_bytes"]).random_bytes(32)
    salt = new_salt()
    new_kek = derive_kek(body.new_master_password, salt)
    master_nonce = new_nonce()
    wrapped = aes_gcm_encrypt(new_kek, master_nonce, dek, ("LocalVault|master-wrap|1|" + vault_id + "|1").encode())
    rec_nonce = None
    wrapped_rec = None
    rec_key = None
    if body.create_recovery_key:
        seed = new_recovery_seed()
        rec_kek = derive_recovery_kek(seed, vault_id)
        rec_nonce = new_nonce()
        wrapped_rec = aes_gcm_encrypt(rec_kek, rec_nonce, dek, ("LocalVault|recovery-wrap|1|" + vault_id + "|1").encode())
        rec_key = encode_recovery_key(seed)
    from ..domain.models import VaultPayload
    from ..domain.canonical import canonical_json

    canonical = canonical_json(
        VaultPayload(settings=ctx.vault.plaintext.settings.model_copy(deep=True))
    ).encode("utf-8")
    payload_nonce = new_nonce()
    ciphertext = aes_gcm_encrypt(dek, payload_nonce, canonical, ("LocalVault|payload|1|" + vault_id + "|1|1").encode())
    new_env = VaultEnvelope(
        vault_id=vault_id, schema_version=1, vault_revision=1, format_version=1,
        kdf_algorithm="argon2id", kdf_salt=salt, kdf_m_cost_kib=65536, kdf_t_cost=3, kdf_parallelism=1,
        master_wrap_nonce=master_nonce, wrapped_dek_master=wrapped,
        recovery_wrap_nonce=rec_nonce, wrapped_dek_recovery=wrapped_rec,
        payload_nonce=payload_nonce, payload_ciphertext=ciphertext,
        envelope_checksum=_checksum(vault_id, 1, ciphertext, wrapped),
    )
    with ctx.backups.transaction() as backup_tx:
        backup_tx.write_backup(env, kind="pre_operation", operation="reset_vault")
        ctx.vault._write_envelope(backup_tx.tx, new_env)
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return {"reset": True, "recovery_key": rec_key}


# ---------------- General ----------------

@router.get("/settings/general")
async def general_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    payload = ctx.vault.plaintext
    return payload.settings.model_dump(mode="json")


class GeneralSettingsUpdate(RequestModel):
    language: Optional[Literal["id", "en"]] = None
    tag_filter_mode: Optional[Literal["and", "or"]] = None
    default_sort: Optional[dict] = None
    page_size: Optional[Literal[25, 50, 100]] = None
    warning_acknowledgements: Optional[list[str]] = None


@router.put("/settings/general")
async def general_put(request: Request, body: GeneralSettingsUpdate) -> dict:
    ctx: AppContext = request.app.state.ctx
    _require_unlocked(ctx, request)
    payload = ctx.vault.plaintext
    new_settings = VaultSettings(**{**payload.settings.model_dump(), **body.model_dump(exclude_none=True)})
    # apply via mutate to bump revision
    def fn(p):
        p.settings = new_settings
        return p

    await ctx.vault.mutate(fn)
    # also persist language to config for lock screen
    ctx.config.language = new_settings.language
    ctx.config.save()
    return new_settings.model_dump(mode="json")


# ---------------- Host ----------------

class HostSettings(RequestModel):
    port: Optional[int] = None
    autostart: Optional[bool] = None


@router.get("/settings/host")
async def host_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    return {
        "port": ctx.config.port,
        "autostart": ctx.config.autostart,
        "restart_required": False,
        "lan_access_enabled": True,
        "bind_host": "0.0.0.0",
    }


@router.put("/settings/host")
async def host_put(request: Request, body: HostSettings) -> dict:
    ctx: AppContext = request.app.state.ctx
    require_session(request)
    restart_required = False
    if body.port is not None:
        if not (1024 <= body.port <= 65535):
            raise errors.ValidationError("port must be 1024-65535")
        if body.port != ctx.config.port:
            ctx.config.port = body.port
            restart_required = True
    if body.autostart is not None:
        if ctx.control is not None:
            try:
                ctx.control.request("set_autostart", {"enabled": body.autostart}, timeout=5)
            except Exception as exc:
                raise errors.ProblemError("AUTOSTART_FAILED", "Autostart failed", "The launcher could not update autostart.", 500) from exc
        ctx.config.autostart = body.autostart
    ctx.config.save()
    return {"port": ctx.config.port, "autostart": ctx.config.autostart, "restart_required": restart_required}


def _checksum(vault_id, rev, payload_ct, wrapped):
    import hashlib

    h = hashlib.sha256()
    h.update(vault_id.encode())
    h.update(rev.to_bytes(4, "big"))
    h.update(payload_ct)
    h.update(wrapped)
    return h.digest()
