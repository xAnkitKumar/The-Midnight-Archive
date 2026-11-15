"""Configuration loading and project layout for The Midnight Archive.

Configuration is split in two files:

* ``config/settings.yaml``  -- machine/production parameters (limits, QC gate)
* ``config/brand.yaml``     -- editorial identity (tone, palette, compliance)

Secrets are never read from YAML. They come from environment variables (or a
local ``.env`` file, which is git-ignored).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from midnight_archive.errors import ConfigError

SETTINGS_FILENAME = "settings.yaml"
BRAND_FILENAME = "brand.yaml"

#: Folders created by ``midnight-archive init``. Relative to the project root.
STANDARD_DIRECTORIES: tuple[str, ...] = (
    "data",
    "data/ideas",
    "data/analytics",
    "output",
    "output/scripts",
    "output/storyboards",
    "output/drafts",
    "output/qc",
    "output/rendered",
    "output/approved",
    "output/published",
    "assets",
    "assets/characters",
    "assets/backgrounds",
    "assets/music",
    "assets/sound_effects",
    "assets/fonts",
    "logs",
)

REQUIRED_SETTINGS_SECTIONS = ("app", "paths", "script", "storyboard", "ideas", "qc", "video")
REQUIRED_BRAND_KEYS = ("name", "tagline", "categories", "visual_style", "captions")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Missing configuration file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - depends on malformed input
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def discover_root(start: Path | None = None) -> Path:
    """Find the project root that owns ``config/settings.yaml``.

    ``TMA_HOME`` wins, then an explicit ``start`` directory, then the current
    working directory and its parents, then the package's own parent folder.
    """

    env_home = os.environ.get("TMA_HOME")
    if env_home:
        root = Path(env_home).expanduser().resolve()
        if not (root / "config" / SETTINGS_FILENAME).is_file():
            raise ConfigError(
                f"TMA_HOME points at {root}, but {root / 'config' / SETTINGS_FILENAME} does not exist"
            )
        return root

    candidates: list[Path] = []
    if start is not None:
        candidates.append(Path(start).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    candidates.append(Path(__file__).resolve().parents[1])

    for candidate in candidates:
        for folder in (candidate, *candidate.parents):
            if (folder / "config" / SETTINGS_FILENAME).is_file():
                return folder

    raise ConfigError(
        "Could not find config/settings.yaml. Run commands from the project root, "
        "or set TMA_HOME to the project folder."
    )


def _require_sections(settings: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_SETTINGS_SECTIONS if key not in settings]
    if missing:
        raise ConfigError(
            "config/settings.yaml is missing required sections: " + ", ".join(missing)
        )


def _require_brand(brand: dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_BRAND_KEYS if key not in brand]
    if missing:
        raise ConfigError("config/brand.yaml is missing required keys: " + ", ".join(missing))


@dataclass(frozen=True)
class Settings:
    """Immutable view over the parsed configuration."""

    root: Path
    raw: dict[str, Any]
    brand: dict[str, Any]

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, root: Path | str | None = None) -> "Settings":
        base = Path(root).expanduser().resolve() if root else discover_root()
        if not (base / "config" / SETTINGS_FILENAME).is_file():
            raise ConfigError(
                f"{base} is not a Midnight Archive project (no config/settings.yaml)."
            )
        settings = _read_yaml(base / "config" / SETTINGS_FILENAME)
        brand = _read_yaml(base / "config" / BRAND_FILENAME)
        _require_sections(settings)
        _require_brand(brand)
        # Local, git-ignored developer overrides. Never overrides real env vars.
        load_dotenv(base / ".env", override=False)
        return cls(root=base, raw=settings, brand=brand)

    # ---------------------------------------------------------------- accessors
    def get(self, dotted: str, default: Any = None) -> Any:
        """Read a dotted key such as ``script.max_words``."""

        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def brand_value(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.brand
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def name(self) -> str:
        return str(self.get("app.name", "The Midnight Archive"))

    @property
    def db_path(self) -> Path:
        return self.root / str(self.get("paths.database", "data/archive.db"))

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def directory(self, dotted: str, default: str) -> Path:
        return self.root / str(self.get(dotted, default))

    @property
    def script_settings(self) -> dict[str, Any]:
        return dict(self.get("script", {}))

    @property
    def storyboard_settings(self) -> dict[str, Any]:
        return dict(self.get("storyboard", {}))

    @property
    def ideas_settings(self) -> dict[str, Any]:
        return dict(self.get("ideas", {}))

    @property
    def qc_settings(self) -> dict[str, Any]:
        return dict(self.get("qc", {}))

    @property
    def categories(self) -> list[str]:
        configured = self.get("ideas.categories")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured]
        return list(self.brand.get("categories", {}).keys())

    # ------------------------------------------------------------------ layout
    def ensure_layout(self) -> list[Path]:
        """Create every standard folder. Returns the folders that were created."""

        created: list[Path] = []
        for relative in STANDARD_DIRECTORIES:
            folder = self.root / relative
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                created.append(folder)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return created

    def relative(self, path: Path) -> str:
        """Return a POSIX path relative to the project root for portable metadata."""

        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)
