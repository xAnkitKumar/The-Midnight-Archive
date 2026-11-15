from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_settings() -> Settings:
    """Read-only project settings with the real local voice/font assets."""

    return Settings.load(REPO_ROOT)


@pytest.fixture
def project(tmp_path: Path) -> Settings:
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    for name in ("settings.yaml", "brand.yaml"):
        shutil.copy2(REPO_ROOT / "config" / name, root / "config" / name)
    settings = Settings.load(root)
    settings.ensure_layout()
    return settings


@pytest.fixture
def db(project: Settings):
    database = Database(project.db_path)
    yield database
    database.close()


@pytest.fixture
def pipeline(project: Settings, db: Database) -> Pipeline:
    return Pipeline(project, db)


@pytest.fixture
def selected_video(db: Database):
    video = db.create_video(
        title="The Test Corridor",
        category="mystery",
        premise="A test premise used only by the automated suite.",
    )
    return db.transition(video["id"], "SELECTED")


@pytest.fixture
def demo_script() -> dict:
    return json.loads((REPO_ROOT / "samples" / "demo_script.json").read_text(encoding="utf-8"))


@pytest.fixture
def demo_storyboard() -> dict:
    return json.loads((REPO_ROOT / "samples" / "demo_storyboard.json").read_text(encoding="utf-8"))


def for_video(payload: dict, video_id: str) -> dict:
    """Return a copy of a handoff payload bound to a specific video id."""

    copy = json.loads(json.dumps(payload))
    copy["video_id"] = video_id
    return copy


def quality_payload(video_id: str, total: int = 100, blocking: list[str] | None = None) -> dict:
    """Build a QC payload whose sections sum to ``total`` (100 by default)."""

    base = {
        "hook": 15,
        "originality": 10,
        "coherence": 15,
        "suspense": 15,
        "ending": 15,
        "voice": 10,
        "visual_consistency": 10,
        "subtitle_sync": 5,
        "audio_mix": 5,
    }
    scores = dict(base)
    remaining = max(0, 100 - total)
    for key in ("ending", "suspense", "coherence", "hook"):
        if remaining <= 0:
            break
        cut = min(remaining, scores[key])
        scores[key] -= cut
        remaining -= cut
    return {
        "video_id": video_id,
        "reviewer": "test-reviewer",
        "scores": scores,
        "blocking_issues": blocking or [],
        "notes": "Automated fixture report.",
    }
