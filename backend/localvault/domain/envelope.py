import hashlib
import json
import struct
from dataclasses import dataclass, field
from typing import Optional

MAGIC = b"LOCALVAULT_BACKUP\0"
CONTAINER_VERSION = 2
LEGACY_CONTAINER_VERSION = 1
FORMAT_VERSION = 1
SCHEMA_VERSION = 1
KDF_ALGORITHM = "argon2id"


@dataclass
class VaultEnvelope:
    vault_id: str
    schema_version: int
    vault_revision: int
    format_version: int
    kdf_algorithm: str
    kdf_salt: bytes
    kdf_m_cost_kib: int
    kdf_t_cost: int
    kdf_parallelism: int
    master_wrap_nonce: bytes
    wrapped_dek_master: bytes
    recovery_wrap_nonce: Optional[bytes]
    wrapped_dek_recovery: Optional[bytes]
    payload_nonce: bytes
    payload_ciphertext: bytes
    envelope_checksum: bytes

    def to_row(self) -> dict:
        return {
            "vault_id": self.vault_id,
            "schema_version": self.schema_version,
            "vault_revision": self.vault_revision,
            "format_version": self.format_version,
            "kdf_algorithm": self.kdf_algorithm,
            "kdf_salt": self.kdf_salt,
            "kdf_m_cost_kib": self.kdf_m_cost_kib,
            "kdf_t_cost": self.kdf_t_cost,
            "kdf_parallelism": self.kdf_parallelism,
            "master_wrap_nonce": self.master_wrap_nonce,
            "wrapped_dek_master": self.wrapped_dek_master,
            "recovery_wrap_nonce": self.recovery_wrap_nonce,
            "wrapped_dek_recovery": self.wrapped_dek_recovery,
            "payload_nonce": self.payload_nonce,
            "payload_ciphertext": self.payload_ciphertext,
            "envelope_checksum": self.envelope_checksum,
        }

    @classmethod
    def from_row(cls, row: dict) -> "VaultEnvelope":
        return cls(
            vault_id=row["vault_id"],
            schema_version=row["schema_version"],
            vault_revision=row["vault_revision"],
            format_version=row["format_version"],
            kdf_algorithm=row["kdf_algorithm"],
            kdf_salt=bytes(row["kdf_salt"]),
            kdf_m_cost_kib=row["kdf_m_cost_kib"],
            kdf_t_cost=row["kdf_t_cost"],
            kdf_parallelism=row["kdf_parallelism"],
            master_wrap_nonce=bytes(row["master_wrap_nonce"]),
            wrapped_dek_master=bytes(row["wrapped_dek_master"]),
            recovery_wrap_nonce=bytes(row["recovery_wrap_nonce"]) if row["recovery_wrap_nonce"] is not None else None,
            wrapped_dek_recovery=bytes(row["wrapped_dek_recovery"]) if row["wrapped_dek_recovery"] is not None else None,
            payload_nonce=bytes(row["payload_nonce"]),
            payload_ciphertext=bytes(row["payload_ciphertext"]),
            envelope_checksum=bytes(row["envelope_checksum"]),
        )


def compute_checksum(envelope: VaultEnvelope) -> bytes:
    return compute_checksum_raw(
        envelope.vault_id,
        envelope.vault_revision,
        envelope.payload_ciphertext,
        envelope.wrapped_dek_master,
    )


def compute_checksum_raw(vault_id: str, vault_revision: int, payload_ciphertext: bytes, wrapped_dek_master: bytes) -> bytes:
    h = hashlib.sha256()
    h.update(vault_id.encode("utf-8"))
    h.update(struct.pack(">i", vault_revision))
    h.update(payload_ciphertext)
    h.update(wrapped_dek_master)
    return h.digest()


# ---------------- .lvbak container -----------------

@dataclass
class BackupManifest:
    format: str = "localvault-backup"
    format_version: int = CONTAINER_VERSION
    backup_id: str = ""
    vault_id: str = ""
    schema_version: int = SCHEMA_VERSION
    vault_revision: int = 0
    created_at: str = ""
    kind: str = "mutation"
    operation: Optional[str] = None
    envelope_sha256: str = ""
    application_version: str = "1.0.0"

    def to_json(self) -> bytes:
        return json.dumps(self.__dict__, separators=(",", ":"), sort_keys=True).encode("utf-8")


def pack_backup(
    manifest: BackupManifest,
    envelope: VaultEnvelope,
    container_version: int = CONTAINER_VERSION,
) -> bytes:
    manifest_bytes = manifest.to_json()
    env_bytes = serialize_envelope(envelope)
    out = bytearray()
    out += MAGIC
    out += struct.pack(">I", container_version)
    out += struct.pack(">I", len(manifest_bytes))
    out += manifest_bytes
    out += struct.pack(">I", len(env_bytes))
    out += env_bytes
    return bytes(out)


def serialize_envelope(env: VaultEnvelope) -> bytes:
    fields = [
        env.vault_id.encode("utf-8"),
        struct.pack(">i", env.schema_version),
        struct.pack(">i", env.vault_revision),
        struct.pack(">i", env.format_version),
        env.kdf_algorithm.encode("utf-8"),
        env.kdf_salt,
        struct.pack(">i", env.kdf_m_cost_kib),
        struct.pack(">i", env.kdf_t_cost),
        struct.pack(">i", env.kdf_parallelism),
        env.master_wrap_nonce,
        env.wrapped_dek_master,
        env.recovery_wrap_nonce or b"",
        env.wrapped_dek_recovery or b"",
        env.payload_nonce,
        env.payload_ciphertext,
        env.envelope_checksum,
    ]
    out = bytearray()
    for f in fields:
        out += struct.pack(">I", len(f))
        out += f
    return bytes(out)


def unpack_backup(data: bytes):
    manifest, envelope, _ = unpack_backup_with_version(data)
    return manifest, envelope


def unpack_backup_with_version(data: bytes):
    if not data.startswith(MAGIC):
        raise ValueError("invalid backup magic")
    pos = len(MAGIC)
    if len(data) < pos + 12:
        raise ValueError("truncated backup header")
    (container_ver,) = struct.unpack_from(">I", data, pos)
    pos += 4
    if container_ver not in (LEGACY_CONTAINER_VERSION, CONTAINER_VERSION):
        raise ValueError("unsupported backup container version")
    (manifest_len,) = struct.unpack_from(">I", data, pos)
    pos += 4
    if manifest_len <= 0 or manifest_len > len(data) - pos:
        raise ValueError("invalid manifest length")
    manifest_bytes = data[pos : pos + manifest_len]
    pos += manifest_len
    if len(data) < pos + 4:
        raise ValueError("truncated envelope header")
    (env_len,) = struct.unpack_from(">I", data, pos)
    pos += 4
    if env_len <= 0 or env_len > len(data) - pos:
        raise ValueError("invalid envelope length")
    env_bytes = data[pos : pos + env_len]
    pos += env_len
    if pos != len(data):
        raise ValueError("trailing bytes in backup container")
    raw_manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(raw_manifest, dict):
        raise ValueError("invalid backup manifest")
    manifest = BackupManifest(**raw_manifest)
    if manifest.format != "localvault-backup":
        raise ValueError("invalid backup format")
    if manifest.format_version != container_ver:
        raise ValueError("container and manifest version mismatch")
    env = _unpack_envelope(env_bytes)
    if (
        manifest.vault_id != env.vault_id
        or manifest.schema_version != env.schema_version
        or manifest.vault_revision != env.vault_revision
    ):
        raise ValueError("manifest and envelope metadata mismatch")
    return manifest, env, container_ver


def _unpack_envelope(data: bytes) -> VaultEnvelope:
    pos = 0
    vals = []
    while pos < len(data):
        if len(data) < pos + 4:
            raise ValueError("truncated envelope field header")
        (ln,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if ln > len(data) - pos:
            raise ValueError("truncated envelope field")
        vals.append(data[pos : pos + ln])
        pos += ln
    if pos != len(data) or len(vals) != 16:
        raise ValueError("invalid envelope field count")
    # map to fields excluding recovery (which may be empty)
    vault_id = vals[0].decode("utf-8")
    schema_version = struct.unpack(">i", vals[1])[0]
    vault_revision = struct.unpack(">i", vals[2])[0]
    format_version = struct.unpack(">i", vals[3])[0]
    kdf_algorithm = vals[4].decode("utf-8")
    kdf_salt = vals[5]
    kdf_m_cost_kib = struct.unpack(">i", vals[6])[0]
    kdf_t_cost = struct.unpack(">i", vals[7])[0]
    kdf_parallelism = struct.unpack(">i", vals[8])[0]
    master_wrap_nonce = vals[9]
    wrapped_dek_master = vals[10]
    recovery_wrap_nonce = vals[11] or None
    wrapped_dek_recovery = vals[12] or None
    payload_nonce = vals[13]
    payload_ciphertext = vals[14]
    envelope_checksum = vals[15]
    return VaultEnvelope(
        vault_id=vault_id,
        schema_version=schema_version,
        vault_revision=vault_revision,
        format_version=format_version,
        kdf_algorithm=kdf_algorithm,
        kdf_salt=kdf_salt,
        kdf_m_cost_kib=kdf_m_cost_kib,
        kdf_t_cost=kdf_t_cost,
        kdf_parallelism=kdf_parallelism,
        master_wrap_nonce=master_wrap_nonce,
        wrapped_dek_master=wrapped_dek_master,
        recovery_wrap_nonce=recovery_wrap_nonce,
        wrapped_dek_recovery=wrapped_dek_recovery,
        payload_nonce=payload_nonce,
        payload_ciphertext=payload_ciphertext,
        envelope_checksum=envelope_checksum,
    )
