from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from typing import Literal, Optional

from ..app_context import AppContext
from .. import errors
from ..api.deps import get_user_id
from ..domain.envelope import VaultEnvelope
from ..domain.models import VaultSettings, nfkc_casefold
from ..domain.password_policy import validate_master_password, PasswordPolicyError
from ..crypto.kdf import derive_kek, new_salt, verify_kek
from ..crypto.aes import aes_gcm_encrypt, aes_gcm_decrypt
from ..crypto.recovery import derive_recovery_kek, new_recovery_seed, encode_recovery_key, decode_recovery_seed
from ..crypto.csprng import new_nonce
from ..services.auth_service import set_master_password

router = APIRouter()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_unlocked(ctx, user_id):
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()


async def _current_env(ctx, user_id):
    row = await ctx.vault._fetch_envelope(user_id)
    if row is None:
        raise errors.NotFoundError("vault envelope not found")
    return VaultEnvelope.from_row(row)


def _master_aad(env):
    return ("LocalVault|master-wrap|1|" + env.vault_id + "|" + str(env.schema_version)).encode()


def _rec_aad(env):
    return ("LocalVault|recovery-wrap|1|" + env.vault_id + "|" + str(env.schema_version)).encode()


@router.get("/settings/security")
async def security_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    env = await _current_env(ctx, user_id)
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
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    if body.new_master_password != body.confirm_new_master_password:
        raise errors.ValidationError("confirmation mismatch")
    try:
        validate_master_password(body.new_master_password, body.confirm_new_master_password, body.weak_password_acknowledged)
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    env = await _current_env(ctx, user_id)
    try:
        kek = derive_kek(body.current_master_password, env.kdf_salt)
        dek = aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
    new_salt_v = new_salt()
    new_kek = derive_kek(body.new_master_password, new_salt_v)
    master_nonce = new_nonce()
    wrapped = aes_gcm_encrypt(new_kek, master_nonce, dek, _master_aad(env))
    new_env = VaultEnvelope(
        vault_id=env.vault_id, schema_version=env.schema_version, vault_revision=env.vault_revision,
        format_version=1, kdf_algorithm="argon2id", kdf_salt=new_salt_v,
        kdf_m_cost_kib=65536, kdf_t_cost=3, kdf_parallelism=1,
        master_wrap_nonce=master_nonce, wrapped_dek_master=wrapped,
        recovery_wrap_nonce=env.recovery_wrap_nonce, wrapped_dek_recovery=env.wrapped_dek_recovery,
        payload_nonce=env.payload_nonce, payload_ciphertext=env.payload_ciphertext,
        envelope_checksum=_checksum(env.vault_id, env.vault_revision, env.payload_ciphertext, wrapped),
    )
    await ctx.backups.write_backup(user_id, env, kind="pre_operation", operation="master_password_change")
    await ctx.vault._write_envelope(user_id, new_env)
    await set_master_password(user_id, body.new_master_password)
    return {"changed": True}


class RecoveryKeyAction(RequestModel):
    action: Literal["enable", "rotate"]
    current_master_password: Optional[str] = None


@router.get("/settings/security/recovery-key")
async def recovery_key_status(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    if not ctx.vault.is_unlocked(user_id):
        raise errors.VaultLocked()
    env = await _current_env(ctx, user_id)
    return {"recovery_key_present": env.recovery_wrap_nonce is not None}


@router.post("/settings/security/recovery-key")
async def recovery_action(request: Request, body: RecoveryKeyAction) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    env = await _current_env(ctx, user_id)
    dek = ctx.vault.get_dek(user_id)
    if dek is None:
        raise errors.VaultLocked()
    mp = body.current_master_password
    if mp is None:
        raise errors.ValidationError("current_master_password is required")
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
    await ctx.backups.write_backup(user_id, env, kind="pre_operation", operation="recovery_" + body.action)
    await ctx.vault._write_envelope(user_id, new_env)
    return {"recovery_key": new_rec_key, "enabled": wrapped_rec is not None}


class RecoveryDisable(RequestModel):
    current_master_password: str


@router.delete("/settings/security/recovery-key", status_code=204)
async def recovery_disable(request: Request, body: RecoveryDisable):
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    env = await _current_env(ctx, user_id)
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
    await ctx.backups.write_backup(user_id, env, kind="pre_operation", operation="recovery_disable")
    await ctx.vault._write_envelope(user_id, new_env)
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
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    if body.confirm_recovery_phrase != "RESET LOCALVAULT":
        raise errors.ValidationError("confirmation phrase must be 'RESET LOCALVAULT'")
    try:
        validate_master_password(body.new_master_password, body.confirm_new_master_password, body.weak_password_acknowledged)
    except PasswordPolicyError as exc:
        raise errors.ValidationError(str(exc)) from exc
    env = await _current_env(ctx, user_id)
    try:
        kek = derive_kek(body.master_password, env.kdf_salt)
        aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_aad(env))
    except Exception:
        raise errors.ReauthRequired()
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
    canonical = canonical_json(VaultPayload(settings=ctx.vault.get_plaintext(user_id).settings.model_copy(deep=True))).encode("utf-8")
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
    await ctx.backups.write_backup(user_id, env, kind="pre_operation", operation="reset_vault")
    await ctx.vault._write_envelope(user_id, new_env)
    ctx.sessions.lock_all()
    ctx.vault.lock_all()
    return {"reset": True, "recovery_key": rec_key}


@router.get("/settings/general")
async def general_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    return ctx.vault.get_plaintext(user_id).settings.model_dump(mode="json")


class GeneralSettingsUpdate(RequestModel):
    language: Optional[Literal["id", "en"]] = None
    tag_filter_mode: Optional[Literal["and", "or"]] = None
    default_sort: Optional[dict] = None
    page_size: Optional[Literal[25, 50, 100]] = None
    warning_acknowledgements: Optional[list[str]] = None


@router.put("/settings/general")
async def general_put(request: Request, body: GeneralSettingsUpdate) -> dict:
    ctx: AppContext = request.app.state.ctx
    user_id = get_user_id(request)
    _require_unlocked(ctx, user_id)
    payload = ctx.vault.get_plaintext(user_id)
    new_settings = VaultSettings(**{**payload.settings.model_dump(), **body.model_dump(exclude_none=True)})

    def fn(p):
        p.settings = new_settings
        return p

    await ctx.vault.mutate(user_id, fn)
    ctx.config.language = new_settings.language
    ctx.config.save()
    return new_settings.model_dump(mode="json")


@router.get("/settings/host")
async def host_get(request: Request) -> dict:
    ctx: AppContext = request.app.state.ctx
    get_user_id(request)
    return {
        "port": ctx.config.port,
        "autostart": ctx.config.autostart,
        "restart_required": False,
        "lan_access_enabled": True,
        "bind_host": "0.0.0.0",
    }


class HostSettings(RequestModel):
    port: Optional[int] = None
    autostart: Optional[bool] = None


@router.put("/settings/host")
async def host_put(request: Request, body: HostSettings) -> dict:
    ctx: AppContext = request.app.state.ctx
    get_user_id(request)
    restart_required = False
    if body.port is not None:
        if not (1024 <= body.port <= 65535):
            raise errors.ValidationError("port must be 1024-65535")
        if body.port != ctx.config.port:
            ctx.config.port = body.port
            restart_required = True
    if body.autostart is not None:
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
