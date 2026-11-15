"""The production pipeline: validated imports, QC, approval and publishing.

Every mutating stage:

1. checks the video's current status and immutability,
2. validates the structured handoff before writing anything,
3. writes a *versioned* artifact (never overwriting a previous file),
4. records the artifact hash and the status event in SQLite,
5. runs under an idempotency key so a retried command cannot duplicate work.

Approved and published videos are read-only forever.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from midnight_archive.asset_manager import AssetManager, sha256_file
from midnight_archive.config import Settings
from midnight_archive.database import IMMUTABLE_STATUSES, Database
from midnight_archive.errors import PipelineError, ValidationRejected
from midnight_archive.models import (
    NarrationMetadata,
    QualityReport,
    RenderMetadata,
    Script,
    Storyboard,
    WordTiming,
)
from midnight_archive.procedural_audio import mix_audio, sfx_plan
from midnight_archive.renderer import VideoRenderer
from midnight_archive.subtitles import build_subtitle_document
from midnight_archive.technical_qc import run_technical_qc
from midnight_archive.voiceover import build_tts_provider, read_wav, voice_info, write_wav
from midnight_archive.quality_check import QualityDecision, evaluate
from midnight_archive.script_editor import Issue, errors_only, validate_script
from midnight_archive.storyboard import validate_storyboard
from midnight_archive.utils import (
    atomic_write_text,
    sha256_text,
    utcnow_iso,
)


@dataclass
class StageResult:
    video: sqlite3.Row
    path: Path | None = None
    warnings: list[Issue] = field(default_factory=list)
    replay: bool = False
    notes: list[str] = field(default_factory=list)
    decision: QualityDecision | None = None
    technical: Any | None = None


def _pydantic_issues(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        messages.append(f"{location}: {error['msg']}")
    return messages


class Pipeline:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    # ------------------------------------------------------------------ helpers
    ARTIFACT_FOLDERS = {"script": "scripts", "storyboard": "storyboards"}

    def _output_dir(self, kind: str) -> Path:
        base = self.settings.root / str(self.settings.get("paths.output", "output"))
        return base / self.ARTIFACT_FOLDERS.get(kind, kind)

    def _assert_mutable(self, video: sqlite3.Row) -> None:
        status = str(video["status"])
        if status in IMMUTABLE_STATUSES:
            raise PipelineError(
                f"{video['id']} is {status}. Approved and published videos are never modified; "
                "create a new video for a new version."
            )

    def _write_artifact(self, video: sqlite3.Row, kind: str, payload: dict[str, Any]) -> tuple[Path, str]:
        version = self.db.next_artifact_version(str(video["id"]), kind)
        folder = self._output_dir(kind)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{video['id']}-{video['slug']}-v{version}.json"
        if path.exists():  # pragma: no cover - guarded by versioning
            raise PipelineError(f"Refusing to overwrite existing artifact {path}")
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        atomic_write_text(path, text)
        digest = sha256_text(text)
        self.db.add_artifact(str(video["id"]), kind, version, self.settings.relative(path), digest)
        return path, digest

    def rendered_files(self, video_id: str) -> list[Path]:
        folder = self._output_dir("rendered")
        if not folder.is_dir():
            return []
        return sorted(path for path in folder.glob(f"{video_id}*.mp4") if path.is_file())

    # ------------------------------------------------------------- script import
    def import_script(self, video_id: str, payload: dict[str, Any], actor: str = "cli") -> StageResult:
        raw_digest = sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        key = f"import_script:{video_id}:{raw_digest}"
        video = self.db.require_video(video_id)
        self._assert_mutable(video)
        existing_job = self.db.job(key)
        if existing_job is not None and existing_job["status"] == "succeeded":
            return StageResult(
                video=video,
                replay=True,
                notes=["This exact script was already imported; no new artifact was written."],
            )
        if video["status"] not in {"SELECTED", "SCRIPTED"}:
            raise PipelineError(
                f"{video_id} is {video['status']}; a script can only be attached to a SELECTED "
                "or reopened SCRIPTED video."
            )

        def action() -> StageResult:
            current = self.db.require_video(video_id)
            self._assert_mutable(current)
            try:
                script = Script.model_validate(payload)
            except ValidationError as exc:
                raise ValidationRejected("Script failed schema validation", _pydantic_issues(exc)) from exc

            notes: list[str] = []
            if script.video_id and script.video_id != video_id:
                raise ValidationRejected(
                    f"Script belongs to {script.video_id}, not {video_id}"
                )
            if script.video_id is None:
                script = script.model_copy(update={"video_id": video_id})

            if script.title.casefold() != str(current["title"]).casefold():
                notes.append(
                    f"Script title '{script.title}' differs from the registered title "
                    f"'{current['title']}'; the registered title is kept as canonical."
                )

            issues = validate_script(script, self.settings)
            errors = errors_only(issues)
            if errors:
                raise ValidationRejected(
                    "Script rejected by editorial gates", [f"{i.code}: {i.message}" for i in errors]
                )

            payload_json = script.model_dump(mode="json")
            digest = sha256_text(json.dumps(payload_json, sort_keys=True, ensure_ascii=False))
            path, _ = self._write_artifact(current, "script", payload_json)
            self.db.set_script(video_id, payload_json, digest)
            if current["status"] == "SCRIPTED":
                # A revision replaces the working script but does not change stage.
                # The previous script artifact and its hash remain in history.
                updated = self.db.require_video(video_id)
                notes.append(
                    "Revised the working script in place at SCRIPTED; the previous script "
                    "version remains stored."
                )
            else:
                updated = self.db.transition(
                    video_id, "SCRIPTED", actor=actor, reason=f"script import ({path.name})"
                )
            return StageResult(
                video=updated,
                path=path,
                warnings=[i for i in issues if i.level == "warning"],
                notes=notes,
            )

        outcome = self.db.run_job("import_script", key, action, video_id=video_id)
        if outcome.status == "replayed":
            return StageResult(
                video=self.db.require_video(video_id),
                replay=True,
                notes=["This exact script was already imported; no new artifact was written."],
            )
        return action_result(outcome.result)

    # ---------------------------------------------------------- storyboard import
    def import_storyboard(
        self, video_id: str, payload: dict[str, Any], actor: str = "cli"
    ) -> StageResult:
        raw_digest = sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        key = f"import_storyboard:{video_id}:{raw_digest}"
        video = self.db.require_video(video_id)
        self._assert_mutable(video)
        existing_job = self.db.job(key)
        if existing_job is not None and existing_job["status"] == "succeeded":
            return StageResult(
                video=video,
                replay=True,
                notes=["This exact storyboard was already imported; no new artifact was written."],
            )
        if video["status"] != "SCRIPTED":
            raise PipelineError(
                f"{video_id} is {video['status']}; a storyboard can only be attached to a SCRIPTED video."
            )
        if not video["script_json"]:
            raise PipelineError(f"{video_id} has no stored script; import the script first.")

        def action() -> StageResult:
            current = self.db.require_video(video_id)
            self._assert_mutable(current)
            script = Script.model_validate(json.loads(str(current["script_json"])))
            try:
                storyboard = Storyboard.model_validate(payload)
            except ValidationError as exc:
                raise ValidationRejected(
                    "Storyboard failed schema validation", _pydantic_issues(exc)
                ) from exc
            if storyboard.video_id and storyboard.video_id != video_id:
                raise ValidationRejected(
                    f"Storyboard belongs to {storyboard.video_id}, not {video_id}"
                )
            if storyboard.video_id is None:
                storyboard = storyboard.model_copy(update={"video_id": video_id})

            issues = validate_storyboard(storyboard, script, self.settings)
            errors = errors_only(issues)
            if errors:
                raise ValidationRejected(
                    "Storyboard rejected", [f"{i.code}: {i.message}" for i in errors]
                )

            payload_json = storyboard.model_dump(mode="json")
            path, _ = self._write_artifact(current, "storyboard", payload_json)
            self.db.set_storyboard(video_id, payload_json)
            updated = self.db.transition(
                video_id, "STORYBOARD_READY", actor=actor, reason=f"storyboard import ({path.name})"
            )
            return StageResult(
                video=updated,
                path=path,
                warnings=[i for i in issues if i.level == "warning"],
                notes=[f"{len(storyboard.scenes)} scenes, {storyboard.total_duration:.1f}s"],
            )

        outcome = self.db.run_job("import_storyboard", key, action, video_id=video_id)
        if outcome.status == "replayed":
            return StageResult(
                video=self.db.require_video(video_id),
                replay=True,
                notes=["This exact storyboard was already imported; no new artifact was written."],
            )
        return action_result(outcome.result)

    # ------------------------------------------------------------------- assets
    def _asset_manager(self) -> AssetManager:
        return AssetManager(self.settings, self.db)

    def prepare_assets(self, video_id: str, actor: str = "cli") -> StageResult:
        video = self.db.require_video(video_id)
        self._assert_mutable(video)
        if video["status"] != "STORYBOARD_READY":
            raise PipelineError(
                f"{video_id} is {video['status']}; assets require STORYBOARD_READY."
            )
        if not video["storyboard_json"] or not video["script_json"]:
            raise PipelineError(f"{video_id} has no script/storyboard; assets cannot be prepared.")
        storyboard = Storyboard.model_validate(json.loads(str(video["storyboard_json"])))
        script = Script.model_validate(json.loads(str(video["script_json"])))
        key = f"prepare_assets:{video_id}:{sha256_text(str(video['storyboard_json']))}"
        existing = self.db.job(key)
        if existing is not None and existing["status"] == "succeeded":
            return StageResult(
                video=video,
                replay=True,
                notes=["Assets were already prepared for this storyboard."],
            )

        def action() -> StageResult:
            current = self.db.require_video(video_id)
            self._assert_mutable(current)
            if current["status"] != "STORYBOARD_READY":
                raise PipelineError(
                    f"{video_id} is {current['status']}; assets require STORYBOARD_READY."
                )
            manager = self._asset_manager()
            font = manager.ensure_font(video_id)
            voice = manager.ensure_voice(video_id)
            music = manager.ensure_music(video_id, storyboard.total_duration, storyboard.music.bpm)
            sfx = manager.ensure_sfx(video_id)
            images = manager.ensure_stills(video_id, storyboard)
            payload = {
                "video_id": video_id,
                "script_sha256": sha256_text(str(current["script_json"])),
                "storyboard_sha256": sha256_text(str(current["storyboard_json"])),
                "font": self.settings.relative(font),
                "voice_model": self.settings.relative(voice),
                "music": self.settings.relative(music),
                "sfx": {name: self.settings.relative(path) for name, path in sfx.items()},
                "images": [self.settings.relative(path) for path in images],
                "scene_count": len(storyboard.scenes),
                "licences": manager.inventory(video_id),
            }
            path, _ = self._write_artifact(current, "asset_plan", payload)
            updated = self.db.transition(
                video_id,
                "ASSETS_READY",
                actor=actor,
                reason=f"assets ready: {len(images)} images, score, SFX, font ({path.name})",
            )
            return StageResult(
                video=updated,
                path=path,
                notes=[
                    f"Prepared {len(images)} scene stills and {len(sfx)} SFX with commercial-use records.",
                    "Placeholder visuals are original Pillow compositions, not stock images.",
                ],
            )

        outcome = self.db.run_job("prepare_assets", key, action, video_id=video_id)
        if outcome.status == "replayed":
            return StageResult(video=self.db.require_video(video_id), replay=True)
        return action_result(outcome.result)

    # ----------------------------------------------------------------- narration
    def narrate(self, video_id: str, actor: str = "cli") -> StageResult:
        video = self.db.require_video(video_id)
        self._assert_mutable(video)
        if not video["script_json"] or not video["storyboard_json"]:
            raise PipelineError(f"{video_id} is missing its script or storyboard.")
        script = Script.model_validate(json.loads(str(video["script_json"])))
        storyboard = Storyboard.model_validate(json.loads(str(video["storyboard_json"])))
        voice = str(self.settings.get("audio.voice", "en_US-ljspeech-high"))
        voice_config = self.settings.get(f"audio.voices.{voice}")
        if not isinstance(voice_config, dict):
            voice_config = {}
        provider_name = str(
            voice_config.get("provider", self.settings.get("audio.provider", "piper"))
        ).lower()
        length_scale = (
            float(voice_config.get("speed", self.settings.get("audio.length_scale", 1.0)))
            if provider_name == "kokoro"
            else float(self.settings.get("audio.length_scale", 1.0))
        )
        key = f"narrate:{video_id}:{sha256_text(str(video['script_json']))}:{voice}:{length_scale}"
        existing = self.db.job(key)
        if existing is not None and existing["status"] == "succeeded":
            return StageResult(video=video, replay=True, notes=["Narration already exists."])
        if video["status"] != "ASSETS_READY":
            raise PipelineError(
                f"{video_id} is {video['status']}; narration requires ASSETS_READY."
            )
        info = voice_info(self.settings, voice)

        def action() -> StageResult:
            current = self.db.require_video(video_id)
            self._assert_mutable(current)
            if current["status"] != "ASSETS_READY":
                raise PipelineError(
                    f"{video_id} is {current['status']}; narration requires ASSETS_READY."
                )
            manager = self._asset_manager()
            draft = self.settings.root / "output/drafts" / video_id / "audio"
            draft.mkdir(parents=True, exist_ok=True)
            version = self.db.next_artifact_version(video_id, "narration")
            narration_path = draft / f"narration-v{version}.wav"
            srt_path = draft / f"subtitles-v{version}.srt"
            ass_path = draft / f"subtitles-v{version}.ass"
            mix_path = draft / f"mix-v{version}.wav"
            # A previous failed attempt may have left unregistered partials.
            # Artifact versions in SQLite are the source of truth, so a file at
            # this as-yet-unrecorded version cannot be a committed artifact.
            for path in (narration_path, srt_path, ass_path, mix_path):
                if path.exists():
                    path.unlink()

            provider = build_tts_provider(self.settings)
            plan = provider.synthesize(script)
            write_wav(narration_path, plan.samples, plan.sample_rate)
            document = build_subtitle_document(
                plan, script, self.settings, srt_path, ass_path
            )
            words = [
                WordTiming(word=item.word, start=item.start, end=item.end, beat=item.beat)
                for item in document.words
            ]
            metadata = plan.metadata(
                video_id,
                length_scale=length_scale,
                words=words,
                alignment_method=document.method,
            )

            asset_plan_row = self.db.list_artifacts(video_id, "asset_plan")
            if not asset_plan_row:
                raise PipelineError("No asset plan found; run prepare-assets first.")
            asset_plan = json.loads(
                (self.settings.root / str(asset_plan_row[-1]["path"])).read_text(encoding="utf-8")
            )
            music_path = self.settings.root / str(asset_plan["music"])
            sfx_library = {
                name: self.settings.root / str(path)
                for name, path in asset_plan["sfx"].items()
            }
            mix_plan = sfx_plan(storyboard, sfx_library)
            mix_audio(
                narration_path,
                music_path,
                mix_plan,
                mix_path,
                duration=plan.duration,
                settings=self.settings,
            )

            narrative_path, narrative_digest = self._write_artifact(
                current, "narration_metadata", metadata.model_dump(mode="json")
            )
            self.db.add_artifact(
                video_id,
                "narration",
                version,
                self.settings.relative(narration_path),
                sha256_file(narration_path),
            )
            self.db.add_artifact(
                video_id,
                "subtitles",
                version,
                self.settings.relative(srt_path),
                sha256_text(srt_path.read_text(encoding="utf-8")),
            )
            self.db.add_artifact(
                video_id,
                "subtitle_stylesheet",
                version,
                self.settings.relative(ass_path),
                sha256_text(ass_path.read_text(encoding="utf-8-sig")),
            )
            self.db.add_artifact(
                video_id,
                "audio_mix",
                version,
                self.settings.relative(mix_path),
                sha256_file(mix_path),
            )
            manager.register_narration(video_id, narration_path, voice)
            manager.register_subtitles(video_id, srt_path, ass_path)
            manager.register_mix(video_id, mix_path)
            updated = self.db.transition(
                video_id,
                "AUDIO_READY",
                actor=actor,
                reason=f"narration {plan.duration:.2f}s, {len(document.cues)} cues, voice {voice}",
            )
            return StageResult(
                video=updated,
                path=narrative_path,
                notes=[
                    f"Narration {plan.duration:.2f}s, {len(document.cues)} subtitle cues.",
                    f"Alignment: {document.method}; warnings: {len(document.warnings)}.",
                    f"TTS: {plan.provider} / {plan.voice.name}; licence {plan.voice.license}.",
                    f"Audio metadata: {self.settings.relative(narrative_path)} ({narrative_digest[:12]}).",
                ],
            )

        outcome = self.db.run_job("narrate", key, action, video_id=video_id)
        if outcome.status == "replayed":
            return StageResult(video=self.db.require_video(video_id), replay=True)
        return action_result(outcome.result)

    # --------------------------------------------------------------------- render
    def render_video(self, video_id: str, actor: str = "cli") -> StageResult:
        video = self.db.require_video(video_id)
        self._assert_mutable(video)
        if video["status"] != "AUDIO_READY":
            raise PipelineError(
                f"{video_id} is {video['status']}; rendering requires AUDIO_READY."
            )
        if not video["storyboard_json"]:
            raise PipelineError(f"{video_id} has no storyboard")
        storyboard = Storyboard.model_validate(json.loads(str(video["storyboard_json"])))
        narration_rows = self.db.list_artifacts(video_id, "narration_metadata")
        if not narration_rows:
            raise PipelineError(f"{video_id} has no narration metadata")
        metadata_path = self.settings.root / str(narration_rows[-1]["path"])
        metadata = NarrationMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        srt_rows = self.db.list_artifacts(video_id, "subtitles")
        ass_rows = self.db.list_artifacts(video_id, "subtitle_stylesheet")
        mix_rows = self.db.list_artifacts(video_id, "audio_mix")
        narration_rows = self.db.list_artifacts(video_id, "narration")
        image_rows = self.db.list_assets(video_id, "image")
        if not srt_rows or not ass_rows or not mix_rows or not narration_rows:
            raise PipelineError(f"{video_id} is missing audio/subtitle artifacts for rendering")
        images = sorted(
            (self.settings.root / str(row["path"]) for row in image_rows),
            key=lambda path: path.name,
        )
        if len(images) != len(storyboard.scenes):
            raise PipelineError(
                f"Expected {len(storyboard.scenes)} images, found {len(images)}; re-run prepare-assets."
            )
        srt_path = self.settings.root / str(srt_rows[-1]["path"])
        ass_path = self.settings.root / str(ass_rows[-1]["path"])
        mix_path = self.settings.root / str(mix_rows[-1]["path"])
        narration_path = self.settings.root / str(narration_rows[-1]["path"])
        key = (
            f"render:{video_id}:{metadata_path.name}:{sha256_text(str(video['storyboard_json']))}:"
            f"{self.settings.get('render.crf', 18)}:{self.settings.get('render.preset', 'veryfast')}:"
            f"{ass_rows[-1]['sha256']}"
        )
        existing = self.db.job(key)
        if existing is not None and existing["status"] == "succeeded":
            return StageResult(video=video, replay=True, notes=["Render already exists."])

        def action() -> StageResult:
            current = self.db.require_video(video_id)
            self._assert_mutable(current)
            if current["status"] != "AUDIO_READY":
                raise PipelineError(
                    f"{video_id} is {current['status']}; rendering requires AUDIO_READY."
                )
            version = len(self.rendered_files(video_id)) + 1
            output_path = self._output_dir("rendered") / f"{video_id}-{video['slug']}-v{version}.mp4"
            while output_path.exists():
                version += 1
                output_path = self._output_dir("rendered") / f"{video_id}-{video['slug']}-v{version}.mp4"
            renderer = VideoRenderer(self.settings)
            result = renderer.render(
                video_id,
                storyboard,
                images,
                ass_path,
                mix_path,
                narration_path,
                output_path,
            )
            render_json, _ = self._write_artifact(
                current, "render_metadata", result.metadata.model_dump(mode="json")
            )
            self.db.add_artifact(
                video_id,
                "render",
                version,
                self.settings.relative(result.mp4_path),
                sha256_file(result.mp4_path),
            )
            updated = self.db.transition(
                video_id,
                "RENDERED",
                actor=actor,
                reason=f"render v{version}: {result.metadata.duration:.2f}s {self.settings.get('render.width', 1080)}x{self.settings.get('render.height', 1920)}",
            )
            return StageResult(
                video=updated,
                path=result.mp4_path,
                notes=[
                    f"Rendered {result.metadata.duration:.2f}s at {result.metadata.width}x{result.metadata.height}, {result.metadata.fps} fps.",
                    f"Metadata: {self.settings.relative(render_json)}.",
                    f"File: {self.settings.relative(result.mp4_path)} ({result.mp4_path.stat().st_size / 1_000_000:.2f} MB).",
                ],
            )

        outcome = self.db.run_job("render", key, action, video_id=video_id, max_attempts=1)
        if outcome.status == "replayed":
            return StageResult(video=self.db.require_video(video_id), replay=True)
        return action_result(outcome.result)

    # --------------------------------------------------------------- technical QC
    def technical_qc(self, video_id: str, actor: str = "qc") -> StageResult:
        video = self.db.require_video(video_id)
        if video["status"] != "RENDERED":
            raise PipelineError(
                f"{video_id} is {video['status']}; technical QC runs only on a RENDERED video."
            )
        render_rows = self.db.list_artifacts(video_id, "render")
        metadata_rows = self.db.list_artifacts(video_id, "render_metadata")
        if not render_rows or not metadata_rows:
            raise PipelineError(f"{video_id} has no render artifact to inspect")
        mp4_path = self.settings.root / str(render_rows[-1]["path"])
        render = RenderMetadata.model_validate_json(
            (self.settings.root / str(metadata_rows[-1]["path"])).read_text(encoding="utf-8")
        )
        narration_rows = self.db.list_artifacts(video_id, "narration_metadata")
        srt_rows = self.db.list_artifacts(video_id, "subtitles")
        if not narration_rows or not srt_rows:
            raise PipelineError(f"{video_id} is missing narration/subtitle metadata")
        narration = NarrationMetadata.model_validate_json(
            (self.settings.root / str(narration_rows[-1]["path"])).read_text(encoding="utf-8")
        )
        script = Script.model_validate(json.loads(str(video["script_json"])))
        storyboard = Storyboard.model_validate(json.loads(str(video["storyboard_json"])))
        report = run_technical_qc(
            video_id,
            mp4_path,
            self.settings.root / str(srt_rows[-1]["path"]),
            narration,
            script,
            render,
            self.settings,
            expected_scene_count=len(storyboard.scenes),
        )
        report_path, _ = self._write_artifact(
            video, "technical_qc", report.model_dump(mode="json")
        )
        self.db.add_technical_check(
            video_id,
            self.settings.relative(mp4_path),
            report.passed,
            len(report.checks),
            report.model_dump(mode="json"),
        )
        notes = [f"{len(report.checks) - len(report.failed_checks)}/{len(report.checks)} technical checks passed."]
        notes += [f"FAILED {issue}" for issue in report.blocking_issues]
        return StageResult(
            video=video, path=report_path, notes=notes, replay=False, technical=report
        )

    # -------------------------------------------------------------------- QC gate
    def record_quality(self, video_id: str, payload: dict[str, Any], actor: str = "qc") -> StageResult:
        video = self.db.require_video(video_id)
        if video["status"] != "RENDERED":
            raise PipelineError(
                f"{video_id} is {video['status']}; QC runs only on a RENDERED video."
            )
        try:
            report = QualityReport.model_validate(payload)
        except ValidationError as exc:
            raise ValidationRejected("QC report failed schema validation", _pydantic_issues(exc)) from exc
        if report.video_id != video_id:
            raise ValidationRejected(f"QC report belongs to {report.video_id}, not {video_id}")
        technical = self.db.latest_technical_check(video_id)
        if technical is None or not bool(technical["passed"]):
            raise PipelineError(
                f"{video_id} has no passing technical QC report. Run `qc-check --video {video_id}` first."
            )
        renders = self.db.list_artifacts(video_id, "render")
        latest_render = str(renders[-1]["path"]) if renders else ""
        if str(technical["mp4_path"]) != latest_render:
            raise PipelineError(
                "The technical QC report does not belong to the latest render; re-run qc-check."
            )

        decision = evaluate(report, self.settings)
        self.db.add_quality_report(
            video_id,
            report.reviewer,
            report.total,
            decision.verdict,
            report.model_dump(mode="json"),
        )
        self.db.set_latest_qc(video_id, report.total, decision.verdict)
        updated = self.db.transition(
            video_id,
            "QUALITY_CHECKED",
            actor=actor,
            reason=f"QC {decision.verdict}: {report.total}/100",
        )
        if decision.passed:
            updated = self.db.transition(
                video_id, "AWAITING_APPROVAL", actor=actor, reason="QC gate passed"
            )
        return StageResult(video=updated, decision=decision, notes=decision.failures)

    # -------------------------------------------------------------------- approval
    def approve(self, video_id: str, reviewer: str = "owner", actor: str = "human") -> StageResult:
        video = self.db.require_video(video_id)
        if video["status"] != "AWAITING_APPROVAL":
            raise PipelineError(
                f"{video_id} is {video['status']}; only AWAITING_APPROVAL videos can be approved."
            )
        report = self.db.latest_quality_report(video_id)
        if report is None:
            raise PipelineError(f"{video_id} has no QC report; approval is blocked.")
        if str(report["verdict"]) != "pass":
            raise PipelineError(
                f"{video_id} last QC verdict is '{report['verdict']}' ({report['total']}/100). Fix and re-run QC."
            )
        technical = self.db.latest_technical_check(video_id)
        if technical is None or not bool(technical["passed"]):
            raise PipelineError(f"{video_id} has no passing technical QC report; approval is blocked.")
        renders = self.db.list_artifacts(video_id, "render")
        if renders and str(technical["mp4_path"]) != str(renders[-1]["path"]):
            raise PipelineError(
                "Technical QC does not match the latest render; re-run qc-check before approval."
            )

        rendered = self.rendered_files(video_id)
        if not rendered:
            raise PipelineError(
                f"No rendered video found for {video_id} in {self._output_dir('rendered')}. "
                "Approval requires the final MP4."
            )

        approved_dir = self._output_dir("approved") / video_id
        if approved_dir.exists() and any(approved_dir.iterdir()):
            raise PipelineError(
                f"{approved_dir} already contains an approved bundle; refusing to overwrite it."
            )
        approved_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for artifact in self.db.list_artifacts(video_id):
            source = self.settings.root / str(artifact["path"])
            if source.is_file() and source.name not in copied:
                shutil.copy2(source, approved_dir / source.name)
                copied.append(source.name)
        for media in rendered:
            if media.name not in copied:
                shutil.copy2(media, approved_dir / media.name)
                copied.append(media.name)
        image_dir = approved_dir / "still-images"
        for row in self.db.list_assets(video_id, "image"):
            source = self.settings.root / str(row["path"])
            if source.is_file():
                image_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, image_dir / source.name)

        manifest = {
            "video_id": video_id,
            "title": video["title"],
            "category": video["category"],
            "approved_at": utcnow_iso(),
            "approved_by": reviewer,
            "qc_total": report["total"],
            "qc_verdict": report["verdict"],
            "files": copied,
        }
        atomic_write_text(
            approved_dir / "approval.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )

        updated = self.db.transition(
            video_id,
            "APPROVED",
            actor=actor,
            reason=f"human approval by {reviewer}; QC {report['total']}/100",
        )
        return StageResult(
            video=updated,
            path=approved_dir,
            notes=[f"Copied {len(copied)} file(s) to {self.settings.relative(approved_dir)}"],
        )

    # --------------------------------------------------------------------- publish
    def publish(
        self,
        video_id: str,
        url: str,
        platform: str = "instagram",
        caption: str | None = None,
        hashtags: list[str] | None = None,
        actor: str = "human",
    ) -> StageResult:
        video = self.db.require_video(video_id)
        if video["status"] != "APPROVED":
            raise PipelineError(
                f"{video_id} is {video['status']}; only APPROVED videos can be marked published."
            )
        if not url.lower().startswith(("https://", "http://")):
            raise ValidationRejected("Publishing URL must start with https:// or http://")

        source_dir = self._output_dir("approved") / video_id
        if not source_dir.is_dir():
            raise PipelineError(f"Approved bundle missing at {self.settings.relative(source_dir)}")
        published_dir = self._output_dir("published") / video_id
        if published_dir.exists() and any(published_dir.iterdir()):
            raise PipelineError(
                f"{published_dir} already exists; published bundles are never overwritten."
            )
        shutil.copytree(source_dir, published_dir)

        self.db.add_publication(video_id, platform, url, caption, hashtags)
        updated = self.db.transition(
            video_id,
            "PUBLISHED",
            actor=actor,
            reason=f"{platform}: {url}",
        )
        return StageResult(
            video=updated,
            path=published_dir,
            notes=[f"Bundle archived at {self.settings.relative(published_dir)}"],
        )


def action_result(outcome: Any) -> StageResult:
    """The job record stores no payload; re-run results are fetched separately."""

    if not isinstance(outcome, StageResult):
        raise PipelineError("Pipeline job returned an unexpected result")
    return outcome
