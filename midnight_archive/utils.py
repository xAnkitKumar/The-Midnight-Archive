"""Small shared helpers: slugs, normalisation, hashing and atomic JSON writes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9']+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """UTC timestamp that sorts lexicographically (``2026-11-14T18:30:00Z``)."""

    return utcnow().isoformat(timespec="seconds").replace("+00:00", "Z")


def utcstamp() -> str:
    """Compact timestamp for filenames, e.g. ``20261114T183000Z``."""

    return utcnow().strftime("%Y%m%dT%H%M%SZ")


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def count_words(text: str) -> int:
    """Count spoken words, ignoring standalone punctuation such as em dashes."""

    return sum(1 for token in text.split() if any(char.isalnum() for char in token))


def normalize_words(text: str) -> list[str]:
    """Lowercase word sequence used to compare narration across artifacts."""

    return _WORD_RE.findall(text.casefold())


def title_key(text: str) -> str:
    """Case/punctuation-insensitive key used to reject duplicate titles."""

    ascii_text = unicodedata.normalize("NFKD", text)
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


def slugify(text: str, max_length: int = 60) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_length].rstrip("-") or "untitled")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def premise_hash(premise: str) -> str:
    """Stable fingerprint of a story premise, ignoring formatting differences."""

    return sha256_text(" ".join(normalize_words(premise)))[:32]


def atomic_write_text(path: Path, content: str) -> Path:
    """Write a file atomically so an interrupted run cannot leave a half file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return path


def atomic_write_json(path: Path, payload: Any) -> Path:
    return atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def pretty_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)
