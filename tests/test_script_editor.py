from __future__ import annotations

import pytest
from pydantic import ValidationError

from midnight_archive.config import Settings
from midnight_archive.models import Beat, Script
from midnight_archive.script_editor import (
    errors_only,
    estimate_duration,
    metrics,
    preflight,
    validate_script,
)


def build_script(beats: list[str], final_line: str | None = None) -> Script:
    return Script(
        title="Test Script",
        category="mystery",
        logline="A test logline long enough to pass validation.",
        narration=[Beat(beat=i, text=text, pause_after_ms=200) for i, text in enumerate(beats, 1)],
        final_line=final_line or beats[-1],
    )


def test_demo_script_passes_all_gates(project: Settings, demo_script: dict) -> None:
    script = Script.model_validate(demo_script)
    assert script.word_count == 128
    assert estimate_duration(script, project) == pytest.approx(54.4, abs=0.2)
    assert errors_only(validate_script(script, project)) == []


def test_demo_script_preflight_is_strong(project: Settings, demo_script: dict) -> None:
    result = preflight(Script.model_validate(demo_script), project)
    assert 0 <= result.score <= 100
    assert result.score >= 80
    assert set(result.breakdown) == {"hook", "pacing", "suspense", "ending", "compliance"}


def test_too_short_script_is_rejected(project: Settings) -> None:
    script = build_script(
        [
            "A door opens.",
            "Nobody is there.",
            "It closes again.",
        ]
    )
    codes = [issue.code for issue in errors_only(validate_script(script, project))]
    assert "script.too_short" in codes
    assert "script.duration_short" in codes


def test_banned_phrase_is_an_error(project: Settings) -> None:
    words = "The corridor was empty for the first time in years and it was all a dream"
    filler = ["The walls stayed quiet and the lights did not move."] * 9
    script = build_script([words + ".", *filler, "He never went back."])
    codes = [issue.code for issue in errors_only(validate_script(script, project))]
    assert "script.banned_phrase" in codes


def test_slow_hook_warns(project: Settings, demo_script: dict) -> None:
    demo_script["narration"][0]["text"] = (
        "Elias Voss opened his front door one ordinary Thursday morning and found a newspaper "
        "that was dated tomorrow."
    )
    script = Script.model_validate(demo_script)
    issues = validate_script(script, project)
    assert any(issue.code == "script.slow_hook" and issue.level == "warning" for issue in issues)


def test_long_sentences_warn(project: Settings, demo_script: dict) -> None:
    demo_script["narration"][0]["text"] = (
        "Elias opened the door and found the newspaper lying there exactly as it had every "
        "single morning for the past eleven years without a single interruption or explanation "
        "that he could ever understand."
    )
    script = Script.model_validate(demo_script)
    issues = validate_script(script, project)
    assert any(issue.code == "script.long_sentence" for issue in issues)


def test_final_line_must_match_last_beat() -> None:
    with pytest.raises(ValidationError):
        Script(
            title="Mismatch",
            category="mystery",
            logline="A logline that is long enough for validation.",
            narration=[
                Beat(beat=1, text="First line here."),
                Beat(beat=2, text="Second line here."),
                Beat(beat=3, text="Third line here."),
            ],
            final_line="A different ending.",
        )


def test_adaptation_requires_source() -> None:
    with pytest.raises(ValidationError):
        Script(
            title="Adapted",
            category="mystery",
            logline="An adaptation missing its source reference.",
            source={"type": "public_domain_adaptation"},
            narration=[
                Beat(beat=1, text="First line here."),
                Beat(beat=2, text="Second line here."),
                Beat(beat=3, text="Third line here."),
            ],
            final_line="Third line here.",
        )


def test_metrics_report_structure(project: Settings, demo_script: dict) -> None:
    data = metrics(Script.model_validate(demo_script), project)
    assert data.beat_count == 16
    assert data.sentence_count >= 10
    assert data.longest_sentence_words <= 22
    assert data.as_dict()["word_count"] == 128
