import asyncio
import hashlib
import os
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

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
from ..db import get_meta, set_meta
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
    def __init__(self, conn, data_dir: str, backup_manager: BackupManager, session_manager: SessionManager) -> None:
        self.conn = conn
        self.data_dir = data_dir
        self.backups = backup_manager
        self.sessions = session_manager
        self._lock = asyncio.Lock()
        self._plaintext: Optional[VaultPayload] = None
        self._dek: Optional[bytes] = None
        self._vault_id: Optional[str] = None
        self._setup_completed = False
        self._last_daily_date: Optional[str] = None
        self._loaded = False

    # ---- lifecycle -------------------------------------------------------

    def load(self) -> None:
        flag = get_meta(self.conn, "setup_completed")
        self._setup_completed = flag == "1"
        self._loaded = True

    @property
    def setup_completed(self) -> bool:
        return self._setup_completed

    @property
    def vault_id(self) -> Optional[str]:
        return self._vault_id

    @property
    def plaintext(self) -> VaultPayload:
        if self._plaintext is None:
            raise errors.VaultLocked("Vault is locked")
        return self._plaintext

    def is_unlocked(self) -> bool:
        return self._plaintext is not None and self._dek is not None

    # ---- setup -----------------------------------------------------------

    async def setup(
        self,
        master_password: str,
        confirm: str,
        create_recovery: bool,
        language: str,
        weak_ack: bool,
    ) -> dict:
        try:
            validate_master_password(master_password, confirm, weak_ack)
        except PasswordPolicyError as exc:
            raise errors.ValidationError(str(exc)) from exc
        # No composition rules (SEC-004); weak allowed after ack
        async with self._lock:
            if self._setup_completed:
                raise errors.SetupAlreadyCompleted()
            # Race protection via BEGIN IMMEDIATE
            try:
                with self.backups.transaction() as backup_tx:
                    existing = backup_tx.tx.execute("SELECT vault_id FROM vault_envelope WHERE id = 1").fetchone()
                    if existing is not None:
                        raise errors.SetupAlreadyCompleted()
                    env, dek, recovery_key = self._build_new_vault(master_password, create_recovery, language)
                    self._write_envelope(backup_tx.tx, env)
                    set_meta(backup_tx.tx, "setup_completed", "1")
                    # initial backup
                    backup_tx.write_backup(env, kind="mutation")
            except errors.SetupAlreadyCompleted:
                raise
            self._setup_completed = True
            self._vault_id = env.vault_id
            self._dek = dek
            self._plaintext = VaultPayload(settings=VaultSettings(language=language))
            self._last_daily_date = utc_date_str()
            return {
                "vault_id": env.vault_id,
                "recovery_key": recovery_key,
            }

    def _build_new_vault(self, master_password, create_recovery, language):
        import uuid

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
        env = self._encrypt_payload(vault_id, dek, salt, kek, master_nonce, wrapped, rec_nonce, wrapped_rec, payload, 1)
        return env, dek, recovery_key

    def _encrypt_payload(self, vault_id, dek, salt, kek, master_nonce, wrapped, rec_nonce, wrapped_rec, payload, revision):
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
        return env

    # ---- unlock ----------------------------------------------------------

    async def unlock(self, master_password: str) -> bytes:
        async with self._lock:
            row = self.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
            if row is None:
                raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
            env = VaultEnvelope.from_row(dict(row))
            try:
                kek = derive_kek(master_password, env.kdf_salt)
                dek = aes_gcm_decrypt(kek, env.master_wrap_nonce, env.wrapped_dek_master, _master_wrap_aad(env.vault_id, env.schema_version))
            except Exception:
                raise errors.ProblemError("UNLOCK_FAILED", "Unlock failed", "Invalid master password or corrupt envelope", 401)
            payload = self._decrypt_payload(env, dek)
            self._dek = dek
            self._vault_id = env.vault_id
            self._plaintext = payload
            self._last_daily_date = utc_date_str()
        # Purging mutates the vault and acquires the same lock, so it must run
        # after the unlock critical section has been released.
        await self.purge_expired_trash()
        return dek

    async def purge_expired_trash(self) -> int:
        """TRS-003: purge items whose deleted_at + 30 days <= now. Called after unlock."""
        from datetime import datetime, timezone, timedelta

        if self._plaintext is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        to_purge = []
        for c in self._plaintext.credentials:
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

        await self.mutate(fn)
        return len(to_purge)

    async def unlock_with_recovery(
        self,
        recovery_key: str,
        new_master_password: str,
        confirm_new_master_password: str,
        weak_acknowledged: bool,
    ) -> bytes:
        try:
            validate_master_password(
                new_master_password,
                confirm_new_master_password,
                weak_acknowledged,
            )
        except PasswordPolicyError as exc:
            raise errors.ValidationError(str(exc)) from exc
        async with self._lock:
            row = self.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
            if row is None:
                raise errors.ProblemError("VAULT_NOT_FOUND", "No vault", "Vault not set up", 404)
            env = VaultEnvelope.from_row(dict(row))
            if env.wrapped_dek_recovery is None or env.recovery_wrap_nonce is None:
                raise errors.ProblemError("RECOVERY_DISABLED", "Recovery disabled", "No recovery key is enabled", 400)
            try:
                seed = decode_recovery_seed(recovery_key)
                rec_kek = derive_recovery_kek(seed, env.vault_id)
                dek = aes_gcm_decrypt(rec_kek, env.recovery_wrap_nonce, env.wrapped_dek_recovery, _recovery_wrap_aad(env.vault_id, env.schema_version))
            except Exception:
                raise errors.ProblemError("RECOVERY_FAILED", "Recovery failed", "Invalid recovery key", 401)
            # Recovery rotates master password and recovery key
            new_salt_v = new_salt()
            new_kek = derive_kek(new_master_password, new_salt_v)
            master_nonce = new_nonce()
            wrapped = aes_gcm_encrypt(new_kek, master_nonce, dek, _master_wrap_aad(env.vault_id, env.schema_version))
            new_seed = new_recovery_seed()
            rec_kek2 = derive_recovery_kek(new_seed, env.vault_id)
            rec_nonce = new_nonce()
            wrapped_rec = aes_gcm_encrypt(rec_kek2, rec_nonce, dek, _recovery_wrap_aad(env.vault_id, env.schema_version))
            new_rec_key = encode_recovery_key(new_seed)
            try:
                with self.backups.transaction() as backup_tx:
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
                    backup_tx.write_backup(
                        env, kind="pre_operation", operation="recovery"
                    )
                    self._write_envelope(backup_tx.tx, env2)
            except Exception:
                raise errors.StorageError("Failed to apply recovery rotation")
            self._dek = dek
            self._vault_id = env.vault_id
            self._plaintext = self._decrypt_payload(env2, dek)
            self._last_daily_date = utc_date_str()
            return new_rec_key

    def _decrypt_payload(self, env: VaultEnvelope, dek: bytes) -> VaultPayload:
        try:
            plain = aes_gcm_decrypt(dek, env.payload_nonce, env.payload_ciphertext, _payload_aad(env.vault_id, env.schema_version, env.vault_revision))
        except Exception:
            raise errors.ProblemError("ENVELOPE_AUTH_FAILED", "Auth failed", "Payload authentication failed", 400)
        return VaultPayload.model_validate_json(plain)

    # ---- mutation core ---------------------------------------------------

    async def mutate(self, fn, pre_operation: str | None = None) -> tuple[VaultPayload, int]:
        """Apply a mutation atomically: clone -> N+1 -> encrypt -> backup -> commit -> broadcast.

        When ``pre_operation`` is given, a pre-operation backup of the CURRENT
        envelope is written inside the same transaction before applying the change.
        """
        async with self._lock:
            current = self.plaintext
            if current is None or self._dek is None:
                raise errors.VaultLocked()
            base_revision = self._current_envelope_revision()
            new_revision = base_revision + 1
            try:
                candidate = fn(current.model_copy(deep=True))
                new_payload = VaultPayload.model_validate(
                    candidate.model_dump(mode="python")
                )
                validate_payload_size(new_payload)
            except errors.ProblemError:
                raise
            except Exception as exc:
                raise errors.ValidationError(str(exc)) from exc
            env = self._encrypt_with_current(new_payload, new_revision)
            try:
                with self.backups.transaction() as backup_tx:
                    if pre_operation is not None:
                        cur = self._current_envelope()
                        if cur is not None:
                            backup_tx.write_backup(
                                cur,
                                kind="pre_operation",
                                operation=pre_operation,
                            )
                    self._write_envelope(backup_tx.tx, env)
                    backup_tx.write_backup(env, kind="mutation")
            except Exception as e:
                raise errors.StorageError(f"Mutation failed: {e}")
            self._plaintext = new_payload
            # retention + daily (best-effort)
            self._maybe_daily_snapshot(env)
            self.backups.apply_retention()
            self.sessions.broadcast(
                {
                    "event_id": str(uuid.uuid4()),
                    "type": "vault.changed",
                    "entity_type": None,
                    "entity_id": None,
                    "entity_revision": None,
                    "vault_revision": new_revision,
                    "occurred_at": now_utc(),
                }
            )
            return new_payload, new_revision

    def _encrypt_with_current(self, payload, revision):
        row = self.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
        env = VaultEnvelope.from_row(dict(row))
        canonical = canonical_json(payload).encode("utf-8")
        payload_nonce = new_nonce()
        ciphertext = aes_gcm_encrypt(self._dek, payload_nonce, canonical, _payload_aad(env.vault_id, env.schema_version, revision))
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

    def _current_envelope_revision(self) -> int:
        row = self.conn.execute("SELECT vault_revision FROM vault_envelope WHERE id = 1").fetchone()
        return row["vault_revision"] if row else 0

    def _current_envelope(self) -> VaultEnvelope | None:
        row = self.conn.execute("SELECT * FROM vault_envelope WHERE id = 1").fetchone()
        return VaultEnvelope.from_row(dict(row)) if row else None

    def _write_envelope(self, tx, env: VaultEnvelope) -> None:
        row = env.to_row()
        tx.execute(
            """
            INSERT INTO vault_envelope(
                id, vault_id, schema_version, vault_revision, format_version,
                kdf_algorithm, kdf_salt, kdf_m_cost_kib, kdf_t_cost, kdf_parallelism,
                master_wrap_nonce, wrapped_dek_master, recovery_wrap_nonce, wrapped_dek_recovery,
                payload_nonce, payload_ciphertext, envelope_checksum
            ) VALUES (1, :vault_id, :schema_version, :vault_revision, :format_version,
                :kdf_algorithm, :kdf_salt, :kdf_m_cost_kib, :kdf_t_cost, :kdf_parallelism,
                :master_wrap_nonce, :wrapped_dek_master, :recovery_wrap_nonce, :wrapped_dek_recovery,
                :payload_nonce, :payload_ciphertext, :envelope_checksum)
            ON CONFLICT(id) DO UPDATE SET
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
                envelope_checksum=excluded.envelope_checksum
            """,
            row,
        )

    def _maybe_daily_snapshot(self, env: VaultEnvelope) -> None:
        today = utc_date_str()
        if self._last_daily_date != today:
            try:
                with self.backups.transaction() as backup_tx:
                    backup_tx.write_backup(env, kind="daily")
                self._last_daily_date = today
            except Exception:
                pass

    # ---- lock / cleanup --------------------------------------------------

    def lock_all(self) -> None:
        self._plaintext = None
        self._dek = None
        self._vault_id = None

    def get_current_revision(self) -> int:
        return self._current_envelope_revision()
