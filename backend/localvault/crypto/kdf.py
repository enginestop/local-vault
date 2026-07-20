import hmac
from hashlib import sha256

from argon2 import low_level
from argon2.low_level import Type

from ..crypto.csprng import random_bytes

ARGON2_M_COST_KIB = 65536
ARGON2_T_COST = 3
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32
ARGON2_SALT_LEN = 16


def derive_kek(master_password: str, salt: bytes) -> bytes:
    """Derive a 32-byte master KEK from the master password using Argon2id (SEC-005)."""
    if len(salt) != ARGON2_SALT_LEN:
        raise ValueError("salt must be 16 bytes")
    secret = low_level.hash_secret(
        master_password.encode("utf-8"),
        salt,
        time_cost=ARGON2_T_COST,
        memory_cost=ARGON2_M_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
        version=low_level.ARGON2_VERSION,
    )
    # secret is a modular hash string; extract raw hash bytes (last base64 field)
    parts = secret.split(b"$")
    encoded = parts[-1]
    # base64 (argon2 standard, no padding) decode
    import base64

    pad = b"=" * (-len(encoded) % 4)
    return base64.b64decode(encoded + pad)


def new_salt() -> bytes:
    return random_bytes(ARGON2_SALT_LEN)


def verify_kek(master_password: str, salt: bytes, expected_kek: bytes) -> bool:
    try:
        derived = derive_kek(master_password, salt)
    except Exception:
        return False
    return hmac.compare_digest(derived, expected_kek)
