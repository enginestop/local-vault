import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler

# Patterns that must never appear in logs (SEC-028)
_REDACT_PATTERNS = [
    re.compile(rb"(?i)master[_-]?password"),
    re.compile(rb"(?i)recovery[_-]?key"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(rb"(?i)ticket="),
    re.compile(rb"(?i)token"),
]

REDACTED = b"<REDACTED>"


class UtcFormatter(logging.Formatter):
    converter = time.gmtime


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
        handler.setFormatter(UtcFormatter("%(asctime)sZ %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger


def configure_file_logging(data_dir: str, level: str = "INFO") -> str:
    """Route application logs to a rotating UTF-8 file for windowed builds."""
    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "localvault.log")
    handler = RotatingFileHandler(
        path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(UtcFormatter("%(asctime)sZ %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    for name in ("localvault.api", "localvault.launcher"):
        logger = logging.getLogger(name)
        logger.setLevel(resolved_level)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False
    return path
