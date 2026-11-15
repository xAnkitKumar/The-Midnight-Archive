"""Licence policy for models, voices, fonts, music and images.

The engine licence and the model/content licence are deliberately checked
separately. A GPL-compatible TTS engine does not make an arbitrary voice model
safe to use commercially, and an OFL font does not license the artwork behind a
still image.
"""

from __future__ import annotations

from midnight_archive.errors import ConfigError

#: Normalised identifiers that are acceptable for a monetised Instagram Reel.
#: This is a deliberately small allowlist; reviewers can extend it explicitly.
COMMERCIAL_LICENCES: frozenset[str] = frozenset(
    {
        "public domain",
        "public-domain",
        "cc0",
        "cc0-1.0",
        "cc by 4.0",
        "cc-by-4.0",
        "cc by-sa 4.0",
        "cc-by-sa-4.0",
        "ofl-1.1",
        "sil open font license 1.1",
        "original",
        "original work",
        "mit",
        "apache-2.0",
    }
)

_UNKNOWN = {"", "unknown", "unlicensed", "n/a", "none", "proprietary", "editorial only"}


def normalise_license(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def license_is_commercial(value: str | None) -> bool:
    """Return True only for explicitly recognised commercial-use licences."""

    return normalise_license(value) in COMMERCIAL_LICENCES


def require_commercial_license(
    license_name: str | None,
    *,
    what: str,
    allow_unlicensed: bool = False,
    commercial_use: bool = True,
) -> None:
    """Raise a clear error when an asset may not be used in a monetised video."""

    if allow_unlicensed and normalise_license(license_name) in _UNKNOWN | {"test only"}:
        return
    if not commercial_use:
        raise ConfigError(f"{what} is marked as not cleared for commercial use")
    if not license_is_commercial(license_name):
        raise ConfigError(
            f"{what} has unknown or unsuitable licence {license_name!r}. "
            "Record a recognised commercial licence, or explicitly enable "
            "assets.allow_unlicensed for test-only material."
        )
