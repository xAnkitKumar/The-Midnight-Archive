"""Logging setup.

Logs go to ``logs/midnight.log`` (rotating) and to the console. A redaction
filter removes API keys and bearer tokens before anything is written, so a
careless debug line cannot leak credentials.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from midnight_archive.config import Settings

LOGGER_NAME = "midnight"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret)\s*[:=]\s*[^\s,;]{6,}"),
)


def redact(text: str) -> str:
    """Remove obvious credential shapes from a log line."""

    cleaned = text
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(lambda match: f"{match.group(0).split(':')[0]}: ***" if ":" in match.group(0) else "***", cleaned)

    # Also redact the literal value of any configured secret env var.
    for key, value in os.environ.items():
        upper = key.upper()
        if len(value) < 8:
            continue
        if any(marker in upper for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            cleaned = cleaned.replace(value, "***")
    return cleaned


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib API
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact(message)
        record.args = ()
        return True


def configure_logging(settings: Settings, verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configure and return the application logger (idempotent)."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    log_file = Path(settings.get("paths.logs", "logs")) / "midnight.log"
    if not log_file.is_absolute():
        log_file = settings.root / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=int(settings.get("logging.max_bytes", 2_000_000)),
        backupCount=int(settings.get("logging.backup_count", 3)),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    file_handler.addFilter(RedactionFilter())
    logger.addHandler(file_handler)

    if not quiet:
        console = logging.StreamHandler(stream=sys.stderr)
        console.setLevel(logging.DEBUG if verbose else logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        console.addFilter(RedactionFilter())
        logger.addHandler(console)

    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
