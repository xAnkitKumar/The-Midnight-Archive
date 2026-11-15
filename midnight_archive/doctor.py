"""Environment diagnostics.

``doctor`` answers one question: can this machine actually produce a video?
It checks the Python version, FFmpeg/ffprobe and their encoders, folder
permissions, the SQLite database and the presence of a font for subtitles.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from midnight_archive.config import Settings
from midnight_archive.database import Database


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def resolve_binary(name: str) -> str | None:
    """Find a binary on PATH, or in the per-user WinGet package folder."""

    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if base.is_dir():
            suffix = f"{name}.exe" if os.name == "nt" else name
            matches = sorted(base.glob(f"Gyan.FFmpeg_*/**/bin/{suffix}"))
            if matches:
                return str(matches[0])
    return None


def _ffmpeg_filters(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return completed.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _ffmpeg_encoders(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return completed.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check_environment(settings: Settings) -> list[Check]:
    checks: list[Check] = []

    version = sys.version_info
    checks.append(
        Check(
            "Python",
            version >= (3, 11),
            f"{version.major}.{version.minor}.{version.micro} (requires 3.11+)",
        )
    )

    checks.append(Check("Project root", settings.root.is_dir(), str(settings.root)))

    for label, name in (("FFmpeg", "ffmpeg"), ("ffprobe", "ffprobe")):
        binary = resolve_binary(name)
        checks.append(
            Check(label, binary is not None, binary or "not found on PATH or in WinGet packages")
        )

    ffmpeg = resolve_binary("ffmpeg")
    if ffmpeg:
        encoders = _ffmpeg_encoders(ffmpeg)
        checks.append(
            Check(
                "H.264 encoder",
                "libx264" in encoders,
                "libx264" if "libx264" in encoders else "libx264 missing",
            )
        )
        checks.append(
            Check("AAC encoder", "aac" in encoders, "aac" if "aac" in encoders else "aac missing")
        )
        filters = _ffmpeg_filters(ffmpeg)
        for label, name in (
            ("xfade filter", "xfade"),
            ("zoompan filter", "zoompan"),
            ("ASS subtitle filter", "ass"),
        ):
            checks.append(
                Check(label, name in filters, f"{name} available" if name in filters else f"{name} missing")
            )

    writable_ok = True
    details: list[str] = []
    for relative in ("data", "output", "logs"):
        folder = settings.root / relative
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            writable_ok = False
            details.append(f"{relative}: {exc}")
    checks.append(
        Check("Writable folders", writable_ok, "; ".join(details) or "data, output, logs")
    )

    db_ok = False
    db_detail = str(settings.db_path)
    try:
        with Database(settings.db_path) as db:
            db_ok = db.integrity_ok() and bool(db.sqlite_version())
            db_detail = f"{settings.db_path} (SQLite {db.sqlite_version()})"
    except Exception as exc:  # noqa: BLE001 - report, do not crash the doctor
        db_detail = f"{settings.db_path}: {exc}"
    checks.append(Check("Database", db_ok, db_detail))

    brands = settings.brand.get("categories", {})
    checks.append(
        Check(
            "Brand categories",
            bool(brands),
            ", ".join(brands.keys()) if brands else "no categories in config/brand.yaml",
        )
    )

    for label, module in (
        ("NumPy", "numpy"),
        ("Pillow", "PIL"),
        ("Piper TTS", "piper"),
        ("Kokoro TTS", "kokoro_onnx"),
        ("faster-whisper", "faster_whisper"),
    ):
        installed = importlib.util.find_spec(module) is not None
        checks.append(
            Check(label, installed, "installed" if installed else f"{module} is not installed")
        )

    try:
        from midnight_archive.voiceover import voice_info

        info = voice_info(settings)
        checks.append(
            Check(
                "Narration voice",
                True,
                f"{info.name} via {info.provider} ({info.license}) - "
                f"{settings.relative(info.model_path)}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - report missing licence/model clearly
        checks.append(Check("Narration voice", False, str(exc)))

    font_path = settings.root / str(
        settings.get("render.subtitle.font_file", "assets/fonts/Montserrat-Bold.ttf")
    )
    checks.append(
        Check(
            "Subtitle font",
            font_path.is_file(),
            settings.relative(font_path)
            if font_path.is_file()
            else f"Missing {font_path} (Montserrat OFL)",
        )
    )

    checks.append(
        Check(
            "Paid API gate",
            os.environ.get("TMA_ALLOW_PAID_API", "").lower() not in {"1", "true", "yes"},
            "disabled (offline generation only)"
            if os.environ.get("TMA_ALLOW_PAID_API", "").lower() not in {"1", "true", "yes"}
            else "ENABLED - paid calls are possible",
            required=False,
        )
    )

    return checks


def all_required_passed(checks: list[Check]) -> bool:
    return all(check.ok for check in checks if check.required)
