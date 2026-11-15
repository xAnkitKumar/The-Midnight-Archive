from __future__ import annotations

from pathlib import Path

import pytest

from midnight_archive.config import Settings
from midnight_archive.errors import ConfigError


def test_loads_project_configuration(project: Settings) -> None:
    assert project.name == "The Midnight Archive"
    assert project.brand_value("handle") == "@themidnightarchive"
    assert "psychological_horror" in project.categories
    assert project.get("qc.minimum_total") == 80
    assert project.db_path.is_absolute()
    assert project.db_path.parent.is_dir()


def test_dotted_get_returns_default(project: Settings) -> None:
    assert project.get("does.not.exist", "fallback") == "fallback"
    assert project.brand_value("compliance.rules") != []


def test_layout_creation_is_idempotent(project: Settings) -> None:
    for relative in ("output/scripts", "output/storyboards", "logs", "assets/fonts"):
        assert (project.root / relative).is_dir()
    again = project.ensure_layout()
    assert again == []


def test_missing_configuration_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Settings.load(tmp_path)


def test_relative_paths_are_posix(project: Settings) -> None:
    sample = project.root / "output" / "scripts" / "demo.json"
    assert project.relative(sample) == "output/scripts/demo.json"
