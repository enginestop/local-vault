import hashlib
import hmac

from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from ..crypto.csprng import random_bytes

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
LV_PREFIX = "LV1"


def _crockford_encode(data: bytes) -> str:
    bits = 0
    value = 0
    out = []
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(CROCKFORD_ALPHABET[(value >> bits) & 0x1F])
    if bits > 0:
        out.append(CROCKFORD_ALPHABET[(value << (5 - bits)) & 0x1F])
    return "".join(out)


def _crockford_decode(text: str) -> bytes:
    clean = text.upper().replace("-", "").replace(" ", "")
    clean = clean.replace("O", "0").replace("I", "1").replace("L", "1")
    out = bytearray()
    buffer = 0
    bits = 0
    for ch in clean:
        idx = CROCKFORD_ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"invalid character in recovery key: {ch!r}")
        buffer = (buffer << 5) | idx
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((buffer >> bits) & 0xFF)
    return bytes(out)


def _checksum(seed: bytes) -> str:
    digest = hashlib.sha256(b"LocalVault recovery v1" + seed).digest()
    # first 40 bits (5 bytes) of SHA-256
    return _crockford_encode(digest[:5])


def encode_recovery_key(seed: bytes) -> str:
    """Format canonical: LV1 + 52 char base32 seed + 8 char base32 checksum, grouped by 4 with '-'."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    body = _crockford_encode(seed)
    check = _checksum(seed)
    raw = f"{LV_PREFIX}{body}{check}"
    # group every 4 chars
    groups = [raw[i : i + 4] for i in range(0, len(raw), 4)]
    return "-".join(groups)


def decode_recovery_seed(key: str) -> bytes:
    """Parse a recovery key. Rejects wrong checksum before any crypto (SEC-017)."""
    clean = key.strip().upper().replace(" ", "").replace("-", "")
    if not clean.startswith(LV_PREFIX):
        raise ValueError("invalid recovery key prefix")
    payload = clean[len(LV_PREFIX):]
    if len(payload) != 52 + 8:
        raise ValueError("invalid recovery key length")
    body = payload[:52]
    check = payload[52:]
    seed = _crockford_decode(body)
    if _checksum(seed) != check:
        raise ValueError("invalid recovery key checksum")
    return seed


def derive_recovery_kek(seed: bytes, vault_id: str) -> bytes:
    """HKDF-SHA-256 recovery KEK (SEC-013)."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=vault_id.encode("utf-8"),
        info=b"LocalVault recovery KEK v1",
    )
    return hkdf.derive(seed)


def new_recovery_seed() -> bytes:
    return random_bytes(32)


def constant_time_eq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
