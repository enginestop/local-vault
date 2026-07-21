from localvault.crypto import aes
from localvault.crypto import kdf
from localvault.crypto import recovery
from localvault.crypto import csprng
from localvault.domain import canonical
from localvault.domain.models import VaultPayload, Credential
from localvault.domain.envelope import (
    VaultEnvelope,
    compute_checksum,
    compute_checksum_raw,
    pack_backup,
    unpack_backup,
)
import pytest


def test_aes_roundtrip():
    key = csprng.random_bytes(32)
    nonce = csprng.new_nonce()
    pt = b"secret-data-12345"
    ct = aes.aes_gcm_encrypt(key, nonce, pt, b"aad")
    assert aes.aes_gcm_decrypt(key, nonce, ct, b"aad") == pt


def test_aes_tamper_detected():
    key = csprng.random_bytes(32)
    nonce = csprng.new_nonce()
    ct = aes.aes_gcm_encrypt(key, nonce, b"hello", b"aad")
    bad = bytearray(ct)
    bad[-1] ^= 1
    with pytest.raises(Exception):
        aes.aes_gcm_decrypt(key, nonce, bytes(bad), b"aad")


def test_kdf_derive_and_verify():
    pw = "correct horse battery staple"
    salt = kdf.new_salt()
    kek = kdf.derive_kek(pw, salt)
    assert len(kek) == 32
    assert kdf.verify_kek(pw, salt, kek)
    assert not kdf.verify_kek("wrong", salt, kek)


def test_argon2_params():
    salt = kdf.new_salt()
    kek = kdf.derive_kek("pw", salt)
    # Params are fixed by SEC-005
    assert kdf.ARGON2_M_COST_KIB == 65536
    assert kdf.ARGON2_T_COST == 3
    assert kdf.ARGON2_PARALLELISM == 1
    assert len(kek) == 32


def test_recovery_key_roundtrip():
    seed = recovery.new_recovery_seed()
    key = recovery.encode_recovery_key(seed)
    assert key.startswith("LV1")
    assert recovery.decode_recovery_seed(key) == seed


def test_recovery_key_checksum():
    seed = recovery.new_recovery_seed()
    key = recovery.encode_recovery_key(seed)
    # tamper one char in body (not checksum) should fail decode
    bad = list(key)
    # flip a middle character
    idx = 4
    bad[idx] = "A" if bad[idx] != "A" else "B"
    with pytest.raises(Exception):
        recovery.decode_recovery_seed("".join(bad))


def test_recovery_kek_derivation():
    seed = recovery.new_recovery_seed()
    kek = recovery.derive_recovery_kek(seed, "vault-xyz")
    assert len(kek) == 32
    # deterministic
    assert recovery.derive_recovery_kek(seed, "vault-xyz") == kek
    # vault_id bound
    assert recovery.derive_recovery_kek(seed, "other") != kek


def test_canonical_json_stable():
    cid_a = "aaaaaaaa-0000-0000-0000-000000000001"
    cid_b = "bbbbbbbb-0000-0000-0000-000000000002"
    timestamp = "2026-07-20T00:00:00.000Z"
    a = {"id": cid_a, "name": "A", "username": "b", "created_at": timestamp, "updated_at": timestamp}
    b = {"id": cid_b, "name": "Z", "username": "a", "created_at": timestamp, "updated_at": timestamp}
    p1 = VaultPayload(credentials=[Credential(**b), Credential(**a)])
    p2 = VaultPayload(credentials=[Credential(**a), Credential(**b)])
    # canonical sorts credentials by id, so order-independent
    assert canonical.canonical_json(p1) == canonical.canonical_json(p2)


def test_envelope_checksum_roundtrip():
    env = VaultEnvelope(
        vault_id="v1",
        schema_version=1,
        vault_revision=3,
        format_version=1,
        kdf_algorithm="argon2id",
        kdf_salt=csprng.random_bytes(16),
        kdf_m_cost_kib=65536,
        kdf_t_cost=3,
        kdf_parallelism=1,
        master_wrap_nonce=csprng.new_nonce(),
        wrapped_dek_master=csprng.random_bytes(48),
        recovery_wrap_nonce=csprng.new_nonce(),
        wrapped_dek_recovery=csprng.random_bytes(48),
        payload_nonce=csprng.new_nonce(),
        payload_ciphertext=csprng.random_bytes(64),
        envelope_checksum=compute_checksum_raw("v1", 3, b"payload", b"wrapped"),
    )
    from localvault.domain.envelope import BackupManifest

    manifest = BackupManifest(
        backup_id="b1",
        vault_id="v1",
        schema_version=1,
        vault_revision=3,
        created_at="2026-01-01T00:00:00Z",
        kind="mutation",
        operation=None,
        envelope_sha256="",
        application_version="1.0.0",
    )
    packed = pack_backup(manifest, env)
    man2, env2 = unpack_backup(packed)
    assert env2.envelope_checksum == env.envelope_checksum
    # checksum depends on payload
    assert compute_checksum_raw("v1", 3, b"x", b"y") != compute_checksum_raw("v1", 3, b"z", b"y")
