from __future__ import annotations

import pytest

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import PipelineError
from midnight_archive.pipeline import Pipeline
from midnight_archive.utils import sha256_text

from tests.conftest import for_video, quality_payload


def import_demo(pipeline: Pipeline, demo_script: dict, demo_storyboard: dict, video_id: str) -> None:
    pipeline.import_script(video_id, for_video(demo_script, video_id))
    pipeline.import_storyboard(video_id, for_video(demo_storyboard, video_id))


def test_asset_stage_requires_storyboard_ready(pipeline: Pipeline, selected_video) -> None:
    with pytest.raises(PipelineError, match="STORYBOARD_READY"):
        pipeline.prepare_assets(selected_video["id"])


def test_narration_requires_assets_ready(
    pipeline: Pipeline, selected_video, demo_script: dict, demo_storyboard: dict
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    with pytest.raises(PipelineError, match="ASSETS_READY"):
        pipeline.narrate(video_id)


def test_narrate_replays_successful_job_before_advanced_status_gate(
    pipeline: Pipeline, db: Database, selected_video, demo_script: dict, demo_storyboard: dict
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    voice = str(pipeline.settings.get("audio.voice"))
    voice_config = pipeline.settings.get(f"audio.voices.{voice}") or {}
    provider = str(voice_config.get("provider", pipeline.settings.get("audio.provider", "piper"))).lower()
    length_scale = (
        float(voice_config.get("speed", pipeline.settings.get("audio.length_scale", 1.0)))
        if provider == "kokoro"
        else float(pipeline.settings.get("audio.length_scale", 1.0))
    )
    script_json = str(db.require_video(video_id)["script_json"])
    key = f"narrate:{video_id}:{sha256_text(script_json)}:{voice}:{length_scale}"
    db.run_job("narrate", key, lambda: None, video_id=video_id)
    db.transition(video_id, "ASSETS_READY", actor="test")
    db.transition(video_id, "AUDIO_READY", actor="test")

    result = pipeline.narrate(video_id)

    assert result.replay is True
    assert db.require_video(video_id)["status"] == "AUDIO_READY"


def test_render_requires_audio_ready(
    pipeline: Pipeline, selected_video, demo_script: dict, demo_storyboard: dict
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    with pytest.raises(PipelineError, match="AUDIO_READY"):
        pipeline.render_video(video_id)


def test_creative_qc_requires_passing_technical_report(
    pipeline: Pipeline,
    db: Database,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    for status in ("ASSETS_READY", "AUDIO_READY", "RENDERED"):
        db.transition(video_id, status, actor="test")
    with pytest.raises(PipelineError, match="technical QC"):
        pipeline.record_quality(video_id, quality_payload(video_id, 95))


def test_approval_requires_technical_report(
    pipeline: Pipeline,
    db: Database,
    project: Settings,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    for status in ("ASSETS_READY", "AUDIO_READY", "RENDERED"):
        db.transition(video_id, status, actor="test")
    rendered = project.root / "output" / "rendered" / f"{video_id}-demo.mp4"
    rendered.write_bytes(b"\x00\x00\x00\x18ftypmp42demo")
    # Bypass the pipeline gate only to create a technically unscored QC record,
    # then prove approval still refuses it.
    from midnight_archive.models import QualityReport
    from midnight_archive.quality_check import evaluate

    payload = quality_payload(video_id, 95)
    report = QualityReport.model_validate(payload)
    decision = evaluate(report, project)
    db.add_quality_report(video_id, report.reviewer, report.total, decision.verdict, payload)
    db.transition(video_id, "QUALITY_CHECKED", actor="test")
    db.transition(video_id, "AWAITING_APPROVAL", actor="test")
    with pytest.raises(PipelineError, match="technical QC"):
        pipeline.approve(video_id)
