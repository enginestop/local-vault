import logging
import re

# Patterns that must never appear in logs (SEC-028)
_REDACT_PATTERNS = [
    re.compile(rb"(?i)master[_-]?password"),
    re.compile(rb"(?i)recovery[_-]?key"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(rb"(?i)ticket="),
    re.compile(rb"(?i)token"),
]

REDACTED = b"<REDACTED>"


def redact_bytes(data: bytes) -> bytes:
    out = data
    for pat in _REDACT_PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, bytes):
            record.msg = redact_bytes(record.msg)
        elif isinstance(record.msg, str):
            # redact obvious secret keys in strings
            for pat in _REDACT_PATTERNS:
                record.msg = pat.sub(REDACTED, record.msg.encode("utf-8", "replace")).decode("utf-8", "replace")
        if record.args:
            record.args = tuple(
                redact_bytes(a) if isinstance(a, bytes) else a for a in record.args
            )
        return True


def make_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.addFilter(RedactingFilter())
    # prevent secret propagation to root handlers
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
