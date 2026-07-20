import secrets
import string

from ..crypto.csprng import random_bytes

AMBIGUOUS = set("Il1O0o|\\`'\"")

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/"


class GeneratorError(ValueError):
    pass


def generate(
    length: int = 20,
    lower: bool = True,
    upper: bool = True,
    digits: bool = True,
    symbols: bool = True,
    exclude_ambiguous: bool = False,
) -> str:
    if length < 4 or length > 256:
        raise GeneratorError("length must be 4-256")
    pools = []
    if lower:
        pools.append(LOWER)
    if upper:
        pools.append(UPPER)
    if digits:
        pools.append(DIGITS)
    if symbols:
        pools.append(SYMBOLS)
    if not pools:
        raise GeneratorError("at least one charset required")

    if exclude_ambiguous:
        pools = ["".join(c for c in pool if c not in AMBIGUOUS) for pool in pools]
        pools = [pool for pool in pools if pool]

    # Build full allowed charset
    allowed = []
    for p in pools:
        allowed.append(p)
    # If excluding ambiguous removed a whole pool, re-check non-empty
    allowed = [p for p in allowed if p]
    if not allowed:
        raise GeneratorError("exclude_ambiguous removed all characters")

    # Ensure at least one char from each selected charset when length allows
    result = []
    for p in allowed:
        result.append(p[secrets.randbelow(len(p))])
    # Fill the rest
    all_chars = "".join(allowed)
    while len(result) < length:
        result.append(all_chars[secrets.randbelow(len(all_chars))])

    # Secure Fisher-Yates shuffle
    for i in range(len(result) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        result[i], result[j] = result[j], result[i]

    # If length was less than number of pools, trim (rare: length 4 with 4 pools is fine)
    return "".join(result[:length])
