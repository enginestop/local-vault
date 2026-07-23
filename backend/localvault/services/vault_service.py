import asyncio
import hashlib
import os
import struct
import uuid
from datetime import datetime, timezone
from typing import Optional

from ..database.pool import get_pool
from ..database.schema import get_meta, set_meta
from ..crypto.csprng import random_bytes, new_nonce
from ..crypto.aes import aes_gcm_encrypt, aes_gcm_decrypt
from ..crypto.kdf import derive_kek, new_salt, verify_kek
from ..crypto.recovery import (
    derive_recovery_kek,
    new_recovery_seed,
    encode_recovery_key,
    decode_recovery_seed,
)
from ..domain.models import (
    VaultPayload,
    Credential,
    Category,
    CustomField,
    PasswordHistoryEntry,
    VaultSettings,
    nfkc_casefold,
    now_utc,
    validate_payload_size,
)
from ..domain.password_policy import validate_master_password, PasswordPolicyError
from ..domain.canonical import canonical_json
from ..domain.envelope import (
    VaultEnvelope,
    compute_checksum,
    compute_checksum_raw,
    BackupManifest,
    pack_backup,
)
from .backup_manager import BackupManager
from .session_manager import SessionManager
from .. import errors

SCHEMA_VERSION = 1
APP_VERSION = "1.0.0"


def utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _payload_aad(vault_id: str, schema_version: int, vault_revision: int) -> bytes:
    return b"LocalVault|payload|1|" + vault_id.encode() + b"|" + str(schema_version).encode() + b"|" + str(vault_revision).encode()


def _master_wrap_aad(vault_id: str, schema_version: int) -> bytes:
    return b"LocalVault|master-wrap|1|" + vault_id.encode() + b"|" + str(schema_version).encode()


def _recovery_wrap_aad(vault_id: str, schema_version: int) -> bytes:
    return b"LocalVault|recovery-wrap|1|" + vault_id.encode() + b"|" + str(schema_version).encode()


class VaultService:
    def __init__(self, data_dir: str, backup_manager: BackupManager, session_manager: SessionManager) -> None:
        self.data_dir = data_dir
        self.backups = backup_manager
        self.sessions = session_manager
        self._lock = asyncio.Lock()
        self._user_states: dict[str, dict] = {}
        self._last_daily_dates: dict[str, str] = {}

    # ---- per-user state helpers -------------------------------------------

    def _user_state(self, user_id: str) -> dict:
        state = self._user_states.get(user_id)
        if state is None:
            raise errors.VaultLocked()
        return state

    def is_unlocked(self, user_id: str) -> bool:
        state = self._user_states.get(user_id)
        return state is not None

    def get_plaintext(self, user_id: str) -> VaultPayload:
        state = self._user_state(user_id)
        return state["plaintext"]

    @property
    def plaintext(self) -> VaultPayload:
        """In-process compatibility accessor for the currently unlocked vault.

        This never serializes or exposes plaintext through the HTTP API; API
        routes continue to use the user-scoped ``get_plaintext`` method.
        """
        if len(self._user_states) != 1:
            raise errors.VaultLocked()
        return next(iter(self._user_states.values()))["plaintext"]

    def get_dek(self, user_id: str) -> bytes:
        state = self._user_state(user_id)
        return state["dek"]

    def get_vault_id(self, user_id: str) -> str:
        state = self._user_state(user_id)
        return state["vault_id"]

    # ---- row mapping ------------------------------------------------------

    async def _fetch_envelope(self, user_id: str) -> Optional[dict]:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM vault_envelopes WHERE user_id = $1::uuid", user_id
            )
        return dict(row) if row else None

    async def _write_envelope(self, user_id: str, env: VaultEnvelope) -> None:
        pool = get_pool()
        row = env.to_row()
        row["user_id"] = user_id
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO vault_envelopes(
                    user_id, vault_id, schema_version, vault_revision, format_version,
                    kdf_algorithm, kdf_salt, kdf_m_cost_kib, kdf_t_cost, kdf_parallelism,
                    master_wrap_nonce, wrapped_dek_master,
                    recovery_wrap_nonce, wrapped_dek_recovery,
                    payload_nonce, payload_ciphertext, envelope_checksum
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (user_id) DO UPDATE SET
                    vault_id=excluded.vault_id,
                    schema_version=excluded.schema_version,
                    vault_revision=excluded.vault_revision,
                    format_version=excluded.format_version,
                    kdf_algorithm=excluded.kdf_algorithm,
                    kdf_salt=excluded.kdf_salt,
                    kdf_m_cost_kib=excluded.kdf_m_cost_kib,
                    kdf_t_cost=excluded.kdf_t_cost,
                    kdf_parallelism=excluded.kdf_parallelism,
                    master_wrap_nonce=excluded.master_wrap_nonce,
                    wrapped_dek_master=excluded.wrapped_dek_master,
                    recovery_wrap_nonce=excluded.recovery_wrap_nonce,
                    wrapped_dek_recovery=excluded.wrapped_dek_recovery,
                    payload_nonce=excluded.payload_nonce,
                    payload_ciphertext=excluded.payload_ciphertext,
                    envelope_checksum=excluded.envelope_checksum,
                    updated_at=now()
                """,
                row["user_id"], row["vault_id"], row["schema_version"],
                row["vault_revision"], row["format_version"],
                row["kdf_algorithm"], row["kdf_salt"],
                row["kdf_m_cost_kib"], row["kdf_t_cost"], row["kdf_parallelism"],
                row["master_wrap_nonce"], row["wrapped_dek_master"],
                row["recovery_wrap_nonce"], row["wrapped_dek_recovery"],
                row["payload_nonce"], row["payload_ciphertext"],
                row["envelope_checksum"],
            )

    # ---- setup (per-user vault creation) ----------------------------------

    async def setup(
        self,
        user_id: str,
        master_password: str,
        create_recovery: bool,
        language: str,
    ) -> dict:
        existing = await self._fetch_envelope(user_id)
        if existing is not None:
            raise errors.ProblemError("VAULT_EXISTS", "Vault exists", "User already has a vault", 409)
        vault_id = str(uuid.uuid4())
        dek = random_bytes(32)
        salt = new_salt()
        kek = derive_kek(master_password, salt)
        master_nonce = new_nonce()
        wrapped = aes_gcm_encrypt(kek, master_nonce, dek, _master_wrap_aad(vault_id, SCHEMA_VERSION))
        recovery_key = None
        rec_nonce = None
        wrapped_rec = None
        if create_recovery:
            seed = new_recovery_seed()
            rec_kek = derive_recovery_kek(seed, vault_id)
            rec_nonce = new_nonce()
            wrapped_rec = aes_gcm_encrypt(rec_kek, rec_nonce, dek, _recovery_wrap_aad(vault_id, SCHEMA_VERSION))
            recovery_key = encode_recovery_key(seed)
        payload = VaultPayload(settings=VaultSettings(language=language))
        revision = 1
        canonical = canonical_json(payload).encode("utf-8")
        payload_nonce = new_nonce()
        ciphertext = aes_gcm_encrypt(dek, payload_nonce, canonical, _payload_aad(vault_id, SCHEMA_VERSION, revision))
        env = VaultEnvelope(
            vault_id=vault_id,
            schema_version=SCHEMA_VERSION,
            vault_revision=revision,
            format_version=1,
            kdf_algorithm="argon2id",
            kdf_salt=salt,
            kdf_m_cost_kib=65536,
            kdf_t_cost=3,
            kdf_parallelism=1,
            master_wrap_nonce=master_nonce,
            wrapped_dek_master=wrapped,
            recovery_wrap_nonce=rec_nonce,
            wrapped_dek_recovery=wrapped_rec,
            payload_nonce=payload_nonce,
            payload_ciphertext=ciphertext,
            envelope_checksum=compute_checksum_raw(vault_id, revision, ciphertext, wrapped),
        )
        await self._write_envelope(user_id, env)
        self._user_states[user_id] = {
            "plaintext": payload,
            "dek": dek,
            "vault_id": vault_id,
        }
        self._last_daily_dates[user_id] = utc_date_str()
        return {
            "vault_id": vault_id,
            "recovery_key": recovery_key,
        }

    # ---- unlock -----------------------------------------------------------

    async def unlock(self, user_id: str, master_password: str) -> None:
        row = await self._fetch_envelope(user_id)
        if row is None:
            raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
        env = VaultEnvelope.from_row(row)
        try:
            kek = derive_kek(master_password, env.kdf_salt)
            dek = aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_wrap_aad(env.vault_id, env.schema_version))
        except Exception:
            raise errors.ProblemError("UNLOCK_FAILED", "Unlock failed", "Invalid master password or corrupt envelope", 401)
        payload = self._decrypt_payload(env, dek)
        self._user_states[user_id] = {
            "plaintext": payload,
            "dek": dek,
            "vault_id": env.vault_id,
        }
        self._last_daily_dates[user_id] = utc_date_str()
        await self.purge_expired_trash(user_id)

    async def unlock_with_recovery(
        self,
        user_id: str,
        recovery_key: str,
        new_master_password: str,
        confirm_new_master_password: str,
        weak_acknowledged: bool,
    ) -> str:
        try:
            validate_master_password(
                new_master_password,
                confirm_new_master_password,
                weak_acknowledged,
            )
        except PasswordPolicyError as exc:
            raise errors.ValidationError(str(exc)) from exc
        row = await self._fetch_envelope(user_id)
        if row is None:
            raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
        env = VaultEnvelope.from_row(row)
        if env.wrapped_dek_recovery is None or env.recovery_wrap_nonce is None:
            raise errors.ProblemError("RECOVERY_DISABLED", "Recovery disabled", "No recovery key is enabled", 400)
        try:
            seed = decode_recovery_seed(recovery_key)
            rec_kek = derive_recovery_kek(seed, env.vault_id)
            dek = aes_gcm_decrypt(rec_kek, env.recovery_wrap_nonce, env.wrapped_dek_recovery, _recovery_wrap_aad(env.vault_id, env.schema_version))
        except Exception:
            raise errors.ProblemError("RECOVERY_FAILED", "Recovery failed", "Invalid recovery key", 401)
        new_salt_v = new_salt()
        new_kek = derive_kek(new_master_password, new_salt_v)
        master_nonce = new_nonce()
        wrapped = aes_gcm_encrypt(new_kek, master_nonce, dek, _master_wrap_aad(env.vault_id, env.schema_version))
        new_seed = new_recovery_seed()
        rec_kek2 = derive_recovery_kek(new_seed, env.vault_id)
        rec_nonce = new_nonce()
        wrapped_rec = aes_gcm_encrypt(rec_kek2, rec_nonce, dek, _recovery_wrap_aad(env.vault_id, env.schema_version))
        new_rec_key = encode_recovery_key(new_seed)
        env2 = VaultEnvelope(
            vault_id=env.vault_id,
            schema_version=env.schema_version,
            vault_revision=env.vault_revision,
            format_version=1,
            kdf_algorithm="argon2id",
            kdf_salt=new_salt_v,
            kdf_m_cost_kib=65536,
            kdf_t_cost=3,
            kdf_parallelism=1,
            master_wrap_nonce=master_nonce,
            wrapped_dek_master=wrapped,
            recovery_wrap_nonce=rec_nonce,
            wrapped_dek_recovery=wrapped_rec,
            payload_nonce=env.payload_nonce,
            payload_ciphertext=env.payload_ciphertext,
            envelope_checksum=compute_checksum_raw(env.vault_id, env.vault_revision, env.payload_ciphertext, wrapped),
        )
        await self._write_envelope(user_id, env2)
        self._user_states[user_id] = {
            "plaintext": self._decrypt_payload(env2, dek),
            "dek": dek,
            "vault_id": env.vault_id,
        }
        self._last_daily_dates[user_id] = utc_date_str()
        return new_rec_key

    def _decrypt_payload(self, env: VaultEnvelope, dek: bytes) -> VaultPayload:
        try:
            plain = aes_gcm_decrypt(dek, env.payload_nonce, env.payload_ciphertext, _payload_aad(env.vault_id, env.schema_version, env.vault_revision))
        except Exception:
            raise errors.ProblemError("ENVELOPE_AUTH_FAILED", "Auth failed", "Payload authentication failed", 400)
        return VaultPayload.model_validate_json(plain)

    # ---- mutation core ---------------------------------------------------

    async def mutate(
        self,
        user_id: str,
        fn=None,
        pre_operation: str | None = None,
        *,
        event_type: str = "vault.reload_required",
        entity_type: str | None = None,
        entity_id: str | None = None,
        entity_revision: int | None = None,
    ) -> tuple[VaultPayload, int]:
        # Preserve the old in-process helper shape ``mutate(fn)`` for callers
        # that operate on the single currently unlocked vault.  HTTP routes
        # use the explicit user-scoped form below.
        if fn is None and callable(user_id):
            fn = user_id
            if len(self._user_states) != 1:
                raise errors.VaultLocked()
            user_id = next(iter(self._user_states))
        async with self._lock:
            state = self._user_state(user_id)
            current = state["plaintext"]
            dek = state["dek"]
            vault_id = state["vault_id"]
            base_revision = await self._current_envelope_revision(user_id)
            new_revision = base_revision + 1
            try:
                candidate = fn(current.model_copy(deep=True))
                new_payload = VaultPayload.model_validate(candidate.model_dump(mode="python"))
                validate_payload_size(new_payload)
            except errors.ProblemError:
                raise
            except Exception as exc:
                raise errors.ValidationError(str(exc)) from exc
            env = await self._encrypt_with_current(user_id, new_payload, new_revision, dek, vault_id)
            try:
                if pre_operation is not None:
                    cur = await self._current_envelope_raw(user_id)
                    if cur is not None:
                        await self.backups.write_backup(
                            user_id, cur, kind="pre_operation", operation=pre_operation,
                        )
                await self._write_envelope(user_id, env)
                await self.backups.write_backup(
                    user_id, env, kind="mutation",
                )
            except Exception as e:
                raise errors.StorageError(f"Mutation failed: {e}")
            state["plaintext"] = new_payload
            await self._maybe_daily_snapshot(user_id, env)
            await self.backups.apply_retention(user_id)
            self.sessions.broadcast(
                {
                    "event_id": str(uuid.uuid4()),
                    "type": event_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_revision": entity_revision,
                    "vault_revision": new_revision,
                    "occurred_at": now_utc(),
                }
            )
            return new_payload, new_revision

    async def _encrypt_with_current(self, user_id: str, payload, revision, dek, vault_id):
        row = await self._fetch_envelope(user_id)
        if row is None:
            raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not found", 404)
        env = VaultEnvelope.from_row(row)
        canonical = canonical_json(payload).encode("utf-8")
        payload_nonce = new_nonce()
        ciphertext = aes_gcm_encrypt(dek, payload_nonce, canonical, _payload_aad(env.vault_id, env.schema_version, revision))
        return VaultEnvelope(
            vault_id=env.vault_id,
            schema_version=env.schema_version,
            vault_revision=revision,
            format_version=1,
            kdf_algorithm=env.kdf_algorithm,
            kdf_salt=env.kdf_salt,
            kdf_m_cost_kib=env.kdf_m_cost_kib,
            kdf_t_cost=env.kdf_t_cost,
            kdf_parallelism=env.kdf_parallelism,
            master_wrap_nonce=env.master_wrap_nonce,
            wrapped_dek_master=env.wrapped_dek_master,
            recovery_wrap_nonce=env.recovery_wrap_nonce,
            wrapped_dek_recovery=env.wrapped_dek_recovery,
            payload_nonce=payload_nonce,
            payload_ciphertext=ciphertext,
            envelope_checksum=compute_checksum_raw(env.vault_id, revision, ciphertext, env.wrapped_dek_master),
        )

    async def _current_envelope_revision(self, user_id: str) -> int:
        row = await self._fetch_envelope(user_id)
        return row["vault_revision"] if row else 0

    async def _current_envelope_raw(self, user_id: str):
        row = await self._fetch_envelope(user_id)
        return VaultEnvelope.from_row(row) if row else None

    async def _maybe_daily_snapshot(self, user_id: str, env: VaultEnvelope) -> None:
        today = utc_date_str()
        if self._last_daily_dates.get(user_id) != today:
            try:
                await self.backups.write_backup(user_id, env, kind="daily")
                self._last_daily_dates[user_id] = today
            except Exception:
                pass

    async def purge_expired_trash(self, user_id: str) -> int:
        from datetime import timedelta
        state = self._user_states.get(user_id)
        if state is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        to_purge = []
        for c in state["plaintext"].credentials:
            if c.deleted_at:
                try:
                    dt = datetime.strptime(c.deleted_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                except Exception:
                    dt = None
                if dt and dt <= cutoff:
                    to_purge.append(c.id)
        if not to_purge:
            return 0
        ids = set(to_purge)

        def fn(p):
            p.credentials = [c for c in p.credentials if c.id not in ids]
            return p

        await self.mutate(user_id, fn)
        return len(to_purge)

    # ---- lock / cleanup --------------------------------------------------

    def lock_user(self, user_id: str) -> None:
        self._user_states.pop(user_id, None)
        self._last_daily_dates.pop(user_id, None)

    def lock_all(self) -> None:
        self._user_states.clear()
        self._last_daily_dates.clear()

    async def get_current_revision(self, user_id: str) -> int:
        return await self._current_envelope_revision(user_id)
