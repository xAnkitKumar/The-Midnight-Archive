from __future__ import annotations

import json
import copy

import pytest

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import PipelineError, ValidationRejected
from midnight_archive.pipeline import Pipeline

from tests.conftest import for_video, quality_payload


def import_demo(
    pipeline: Pipeline,
    demo_script: dict,
    demo_storyboard: dict,
    video_id: str,
) -> None:
    pipeline.import_script(video_id, for_video(demo_script, video_id))
    pipeline.import_storyboard(video_id, for_video(demo_storyboard, video_id))


def to_rendered(db: Database, video_id: str) -> None:
    for status in ("ASSETS_READY", "AUDIO_READY", "RENDERED"):
        db.transition(video_id, status, actor="test")


def add_passing_technical(db: Database, video_id: str) -> None:
    """Record the minimum technical gate that real renders must satisfy."""

    path = f"output/rendered/{video_id}-demo.mp4"
    db.add_artifact(video_id, "render", 1, path, "a" * 64)
    db.add_technical_check(video_id, path, True, 1, {"passed": True})


def test_script_import_creates_versioned_artifact(
    pipeline: Pipeline,
    db: Database,
    project: Settings,
    selected_video,
    demo_script: dict,
) -> None:
    result = pipeline.import_script(selected_video["id"], for_video(demo_script, selected_video["id"]))
    assert result.video["status"] == "SCRIPTED"
    assert result.path is not None and result.path.is_file()
    artifacts = db.list_artifacts(selected_video["id"], "script")
    assert len(artifacts) == 1
    assert artifacts[0]["version"] == 1
    stored = json.loads(result.path.read_text(encoding="utf-8"))
    assert "word_count" not in stored
    assert stored["narration"][0]["text"] == "Elias's newspaper was dated tomorrow."


def test_reimporting_identical_script_is_idempotent(
    pipeline: Pipeline,
    db: Database,
    selected_video,
    demo_script: dict,
) -> None:
    payload = for_video(demo_script, selected_video["id"])
    pipeline.import_script(selected_video["id"], payload)
    replay = pipeline.import_script(selected_video["id"], payload)
    assert replay.replay is True
    assert len(db.list_artifacts(selected_video["id"], "script")) == 1


def test_reimporting_revised_script_at_scripted_creates_v2(
    pipeline: Pipeline,
    db: Database,
    selected_video,
    demo_script: dict,
) -> None:
    video_id = selected_video["id"]
    first = pipeline.import_script(video_id, for_video(demo_script, video_id))
    first_path = first.path

    revised = copy.deepcopy(for_video(demo_script, video_id))
    revised["narration"][0]["text"] = "Elias's newspaper was dated tomorrow, again."
    second = pipeline.import_script(video_id, revised)

    assert second.video["status"] == "SCRIPTED"
    assert second.path is not None and second.path != first_path
    assert first_path is not None and first_path.is_file()
    artifacts = db.list_artifacts(video_id, "script")
    assert [row["version"] for row in artifacts] == [1, 2]
    stored = json.loads(db.require_video(video_id)["script_json"])
    assert stored["narration"][0]["text"] == "Elias's newspaper was dated tomorrow, again."


def test_invalid_script_is_rejected_and_nothing_is_written(
    pipeline: Pipeline,
    db: Database,
    selected_video,
    demo_script: dict,
) -> None:
    payload = copy.deepcopy(for_video(demo_script, selected_video["id"]))
    payload["narration"] = [
        {"beat": 1, "text": "A door opens.", "pause_after_ms": 0},
        {"beat": 2, "text": "Nobody is there.", "pause_after_ms": 0},
        {"beat": 3, "text": "It closes again.", "pause_after_ms": 0},
    ]
    payload["final_line"] = "It closes again."
    with pytest.raises(ValidationRejected) as excinfo:
        pipeline.import_script(selected_video["id"], payload)
    assert "script.too_short" in " ".join(str(issue) for issue in excinfo.value.issues)
    assert db.require_video(selected_video["id"])["status"] == "SELECTED"
    assert db.list_artifacts(selected_video["id"]) == []


def test_storyboard_requires_script(
    pipeline: Pipeline, selected_video, demo_storyboard: dict
) -> None:
    with pytest.raises(PipelineError):
        pipeline.import_storyboard(
            selected_video["id"], for_video(demo_storyboard, selected_video["id"])
        )


def test_storyboard_import_reaches_storyboard_ready(
    pipeline: Pipeline,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    import_demo(pipeline, demo_script, demo_storyboard, selected_video["id"])
    assert pipeline.db.require_video(selected_video["id"])["status"] == "STORYBOARD_READY"
    storyboard = json.loads(pipeline.db.require_video(selected_video["id"])["storyboard_json"])
    assert len(storyboard["scenes"]) == 8
    assert "total_duration" not in storyboard


def test_approval_requires_rendered_file(
    pipeline: Pipeline,
    db: Database,
    project: Settings,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    to_rendered(db, video_id)
    add_passing_technical(db, video_id)
    pipeline.record_quality(video_id, quality_payload(video_id, 95))
    assert db.require_video(video_id)["status"] == "AWAITING_APPROVAL"
    with pytest.raises(PipelineError, match="No rendered video"):
        pipeline.approve(video_id)


def test_qc_rejection_blocks_approval(
    pipeline: Pipeline,
    db: Database,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    to_rendered(db, video_id)
    add_passing_technical(db, video_id)
    result = pipeline.record_quality(video_id, quality_payload(video_id, 72))
    assert result.decision is not None and result.decision.verdict == "fail"
    assert db.require_video(video_id)["status"] == "QUALITY_CHECKED"
    with pytest.raises(PipelineError, match="AWAITING_APPROVAL"):
        pipeline.approve(video_id)


def test_approve_and_publish_end_to_end(
    pipeline: Pipeline,
    db: Database,
    project: Settings,
    selected_video,
    demo_script: dict,
    demo_storyboard: dict,
) -> None:
    video_id = selected_video["id"]
    import_demo(pipeline, demo_script, demo_storyboard, video_id)
    to_rendered(db, video_id)
    rendered = project.root / "output" / "rendered" / f"{video_id}-demo.mp4"
    rendered.write_bytes(b"\x00\x00\x00\x18ftypmp42demo")
    add_passing_technical(db, video_id)
    pipeline.record_quality(video_id, quality_payload(video_id, 92))

    approval = pipeline.approve(video_id, reviewer="test-owner")
    assert approval.video["status"] == "APPROVED"
    approved_dir = project.root / "output" / "approved" / video_id
    assert (approved_dir / "approval.json").is_file()
    assert any(path.suffix == ".mp4" for path in approved_dir.iterdir())

    publish = pipeline.publish(video_id, "https://www.instagram.com/reel/abc123/")
    assert publish.video["status"] == "PUBLISHED"
    assert len(db.list_publications(video_id)) == 1
    assert (project.root / "output" / "published" / video_id).is_dir()

    with pytest.raises(PipelineError):
        pipeline.publish(video_id, "https://www.instagram.com/reel/second/")
    with pytest.raises(PipelineError, match="never modified"):
        pipeline.import_script(video_id, for_video(demo_script, video_id))
