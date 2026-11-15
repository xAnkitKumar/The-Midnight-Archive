from __future__ import annotations

import json

from midnight_archive.config import Settings
from midnight_archive.models import QualityReport, Script, Storyboard
from midnight_archive.script_editor import errors_only, estimate_duration, validate_script
from midnight_archive.schemas import export_schemas
from midnight_archive.storyboard import validate_storyboard


def test_demo_fits_the_format(project: Settings, demo_script: dict) -> None:
    script = Script.model_validate(demo_script)
    assert 90 <= script.word_count <= 130
    assert 35 <= estimate_duration(script, project) <= 60
    assert script.source.type == "original"
    assert script.category == "mind_bending"
    assert errors_only(validate_script(script, project)) == []


def test_demo_storyboard_covers_the_script(project: Settings, demo_script: dict, demo_storyboard: dict) -> None:
    board = Storyboard.model_validate(demo_storyboard)
    script = Script.model_validate(demo_script)
    assert len(board.scenes) == 8
    assert errors_only(validate_storyboard(board, script, project)) == []
    for scene in board.scenes:
        assert scene.image_prompt
        assert scene.camera
        assert scene.transition in {"cut", "fade", "dissolve", "whip_pan", "match_cut", "push_in"}


def test_schema_export_matches_models(project: Settings) -> None:
    paths = export_schemas(project)
    names = {path.name for path in paths}
    assert names == {
        "idea.schema.json",
        "idea_session.schema.json",
        "script.schema.json",
        "storyboard.schema.json",
        "quality_report.schema.json",
        "narration_metadata.schema.json",
        "technical_report.schema.json",
        "render_metadata.schema.json",
        "asset_manifest.schema.json",
    }
    script_schema = json.loads((project.root / "schemas" / "script.schema.json").read_text("utf-8"))
    assert "narration" in script_schema["properties"]
    assert script_schema["additionalProperties"] is False


def test_quality_report_rejects_unknown_fields() -> None:
    import pytest
    from pydantic import ValidationError

    payload = {
        "video_id": "TMA-0001",
        "reviewer": "someone",
        "scores": {
            "hook": 10,
            "originality": 8,
            "coherence": 10,
            "suspense": 10,
            "ending": 10,
            "voice": 8,
            "visual_consistency": 8,
            "subtitle_sync": 4,
            "audio_mix": 4,
        },
        "surprise": "extra",
    }
    with pytest.raises(ValidationError):
        QualityReport.model_validate(payload)
