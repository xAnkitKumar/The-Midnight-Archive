from __future__ import annotations

import copy

from midnight_archive.config import Settings
from midnight_archive.models import Script, Storyboard
from midnight_archive.script_editor import errors_only
from midnight_archive.storyboard import metrics, validate_storyboard


def test_demo_storyboard_is_valid(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    script = Script.model_validate(demo_script)
    board = Storyboard.model_validate(demo_storyboard)
    assert errors_only(validate_storyboard(board, script, project)) == []


def test_storyboard_timeline_is_contiguous(demo_storyboard: dict) -> None:
    board = Storyboard.model_validate(demo_storyboard)
    assert board.scenes[0].start == 0
    for previous, current in zip(board.scenes, board.scenes[1:]):
        assert current.start == previous.end
    assert board.total_duration == 54.4


def test_gap_is_reported(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    payload = copy.deepcopy(demo_storyboard)
    payload["scenes"][3]["start"] += 0.5
    board = Storyboard.model_validate(payload)
    issues = validate_storyboard(board, Script.model_validate(demo_script), project)
    assert any(issue.code == "storyboard.timing_break" for issue in issues)


def test_missing_words_are_reported(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    payload = copy.deepcopy(demo_storyboard)
    payload["scenes"][0]["narration"] = "Elias's newspaper was dated tomorrow."
    board = Storyboard.model_validate(payload)
    issues = validate_storyboard(board, Script.model_validate(demo_script), project)
    mismatch = [issue for issue in issues if issue.code == "storyboard.narration_mismatch"]
    assert mismatch and mismatch[0].level == "error"


def test_storyboard_needs_enough_scenes(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    payload = copy.deepcopy(demo_storyboard)
    payload["scenes"] = payload["scenes"][:3]
    payload["scenes"][2]["end"] = 53.6
    board = Storyboard.model_validate(payload)
    codes = [issue.code for issue in validate_storyboard(board, Script.model_validate(demo_script), project)]
    assert "storyboard.few_scenes" in codes or "storyboard.narration_mismatch" in codes


def test_metrics_match_script_estimate(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    data = metrics(
        Storyboard.model_validate(demo_storyboard),
        Script.model_validate(demo_script),
        project,
    )
    assert data.scene_count == 8
    assert abs(data.total_duration - data.estimated_script_duration) < 0.5
