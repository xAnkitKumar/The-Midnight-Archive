from __future__ import annotations

import pytest

from midnight_archive.database import Database, JobOutcome
from midnight_archive.errors import DuplicateError, PipelineError, StatusTransitionError
from midnight_archive.utils import title_key


def test_video_starts_as_idea(db: Database) -> None:
    video = db.create_video(title="First Story", category="mystery")
    assert video["status"] == "IDEA"
    assert video["id"] == "TMA-0001"
    history = db.status_history(video["id"])
    assert [row["to_status"] for row in history] == ["IDEA"]


def test_illegal_transition_is_rejected(db: Database) -> None:
    video = db.create_video(title="Second Story", category="mystery")
    with pytest.raises(StatusTransitionError):
        db.transition(video["id"], "APPROVED")


def test_full_status_chain_and_terminal_state(db: Database) -> None:
    video = db.create_video(title="Chain Story", category="mind_bending")
    chain = [
        "SELECTED",
        "SCRIPTED",
        "STORYBOARD_READY",
        "ASSETS_READY",
        "AUDIO_READY",
        "RENDERED",
        "QUALITY_CHECKED",
        "AWAITING_APPROVAL",
        "APPROVED",
        "PUBLISHED",
    ]
    for status in chain:
        video = db.transition(video["id"], status, actor="test")
        assert video["status"] == status
    with pytest.raises(StatusTransitionError):
        db.transition(video["id"], "APPROVED")
    assert db.status_history(video["id"])[-1]["to_status"] == "PUBLISHED"


def test_duplicate_titles_are_case_and_punctuation_insensitive(db: Database) -> None:
    db.create_video(title="The Midnight Archive", category="mystery")
    with pytest.raises(DuplicateError):
        db.create_video(title="the midnight archive!", category="mystery")
    assert title_key("The Midnight Archive") == title_key("the midnight archive!")


def test_artifact_versions_increment(db: Database) -> None:
    video = db.create_video(title="Artifact Story", category="mystery")
    assert db.next_artifact_version(video["id"], "script") == 1
    db.add_artifact(video["id"], "script", 1, "output/scripts/a.json", "abc123")
    assert db.next_artifact_version(video["id"], "script") == 2
    assert len(db.list_artifacts(video["id"], "script")) == 1


def test_duplicate_script_content_is_blocked(db: Database) -> None:
    first = db.create_video(title="First Script Story", category="mystery")
    second = db.create_video(title="Second Script Story", category="mystery")
    db.set_script(first["id"], {"script": "one"}, "same-digest")
    with pytest.raises(DuplicateError):
        db.set_script(second["id"], {"script": "one"}, "same-digest")


def test_idea_deduplication_by_premise(db: Database) -> None:
    db.add_idea_session("S1", "test", "offline", 1, 2)
    idea = {
        "id": "IDEA-0001",
        "title": "The Unlisted Floor",
        "category": "psychological_horror",
        "premise": "A night porter finds a floor that appears only on Tuesdays.",
        "hook": "There is a floor that only exists on Tuesdays.",
        "twist": "The porter has been living there since 1987.",
        "visual_hook": "A lift panel with one extra button.",
        "scores": {"hook": 8, "originality": 7, "suspense": 8, "visual": 9, "ending": 8},
        "total": 80.0,
        "source": "local_generator",
    }
    duplicate = dict(idea, id="IDEA-0002", title="A Different Title")
    inserted = db.add_ideas("S1", [idea, duplicate])
    assert inserted == ["IDEA-0001"]
    assert len(db.list_ideas()) == 1


def test_job_retries_then_succeeds_and_replays(db: Database) -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    outcome = db.run_job("render", "render:abc", flaky, max_attempts=3)
    assert isinstance(outcome, JobOutcome)
    assert outcome.status == "succeeded"
    assert outcome.attempts == 3
    assert outcome.result == "ok"

    replay = db.run_job("render", "render:abc", flaky, max_attempts=3)
    assert replay.status == "replayed"
    assert attempts["count"] == 3


def test_deterministic_errors_are_not_retried(db: Database) -> None:
    calls = {"count": 0}

    def broken() -> None:
        calls["count"] += 1
        raise PipelineError("no retry")

    with pytest.raises(PipelineError):
        db.run_job("import", "import:bad", broken, max_attempts=3)
    assert calls["count"] == 1
    job = db.job("import:bad")
    assert job is not None and job["status"] == "failed"


def test_database_integrity(db: Database) -> None:
    assert db.integrity_ok()
    assert db.sqlite_version()
