"""Structured handoff models.

These models are the contract between agents. Every handoff is validated with
Pydantic before it touches the database or the filesystem, and the generated
JSON Schemas in ``schemas/`` are exported from these same classes.

Design rules:

* ``extra="forbid"`` -- an unexpected field is a bug in the handoff, not
  something to silently drop.
* Every model carries ``schema_version`` so the contract can evolve.
* Fields that the Python layer can compute (word counts, score totals) are
  computed, never trusted from the handoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from midnight_archive.utils import count_words

SCHEMA_VERSION = "1.0"

Category = Literal["psychological_horror", "mystery", "mind_bending"]
SourceType = Literal["original", "public_domain_adaptation"]
Transition = Literal["cut", "fade", "dissolve", "whip_pan", "match_cut", "push_in"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- ideas
class IdeaScores(StrictModel):
    hook: int = Field(ge=1, le=10)
    originality: int = Field(ge=1, le=10)
    suspense: int = Field(ge=1, le=10)
    visual: int = Field(ge=1, le=10)
    ending: int = Field(ge=1, le=10)


class Idea(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str = Field(pattern=r"^IDEA-\d{4}$")
    title: str = Field(min_length=3, max_length=140)
    category: Category
    premise: str = Field(min_length=20, max_length=600)
    hook: str = Field(min_length=5, max_length=240)
    twist: str = Field(min_length=5, max_length=300)
    visual_hook: str = Field(min_length=5, max_length=300)
    scores: IdeaScores
    total: float = Field(ge=0, le=100)
    source: Literal["local_generator", "llm", "human"] = "local_generator"
    premise_hash: str = Field(min_length=8)
    created_at: datetime = Field(default_factory=utcnow)


class IdeaSession(StrictModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    label: str
    provider: str
    seed: int
    created_at: datetime = Field(default_factory=utcnow)
    ideas: list[Idea] = Field(default_factory=list)


# -------------------------------------------------------------------------- script
class SourceInfo(StrictModel):
    type: SourceType = "original"
    reference: str | None = None
    public_domain: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _adaptation_needs_source(self) -> "SourceInfo":
        if self.type == "public_domain_adaptation":
            if not self.reference:
                raise ValueError(
                    "public-domain adaptations must name the source work in source.reference"
                )
            if not self.public_domain:
                raise ValueError("public_domain must be true for an adaptation")
        return self


class Beat(StrictModel):
    beat: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=400)
    pause_after_ms: int = Field(default=0, ge=0, le=2000)

    @field_validator("text")
    @classmethod
    def _single_line(cls, value: str) -> str:
        return " ".join(value.split())


class Script(StrictModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str | None = None
    title: str = Field(min_length=3, max_length=140)
    category: Category
    logline: str = Field(min_length=10, max_length=300)
    source: SourceInfo = Field(default_factory=SourceInfo)
    narration: list[Beat] = Field(min_length=3, max_length=40)
    final_line: str = Field(min_length=1, max_length=240)
    visual_style: str | None = None
    content_notes: str | None = None
    claims: list[str] = Field(default_factory=list)

    @field_validator("narration")
    @classmethod
    def _beats_are_ordered(cls, beats: list[Beat]) -> list[Beat]:
        for expected, beat in enumerate(beats, start=1):
            if beat.beat != expected:
                raise ValueError("narration beats must be numbered consecutively from 1")
        return beats

    @model_validator(mode="after")
    def _final_line_matches_last_beat(self) -> "Script":
        if self.narration[-1].text.casefold() != self.final_line.casefold():
            raise ValueError("final_line must match the last narration beat exactly")
        return self

    @property
    def word_count(self) -> int:
        return sum(count_words(beat.text) for beat in self.narration)

    @property
    def plain_text(self) -> str:
        return " ".join(beat.text for beat in self.narration)

    @property
    def hook(self) -> str:
        return self.narration[0].text


# ---------------------------------------------------------------------- storyboard
class StyleBible(StrictModel):
    palette: str = Field(min_length=3)
    lighting: str = Field(min_length=3)
    lens: str = Field(min_length=3)
    grain: str = Field(min_length=3)
    negative_prompt: str = Field(min_length=3)


class MusicCue(StrictModel):
    mood: str = Field(min_length=3)
    bpm: int = Field(ge=40, le=160)
    volume_db: float = Field(default=-18.0, ge=-40, le=0)


class Scene(StrictModel):
    scene: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    narration: str = Field(min_length=1)
    visual: str = Field(min_length=15)
    characters: list[str] = Field(default_factory=list)
    environment: str = Field(min_length=3)
    lighting: str = Field(min_length=3)
    camera: str = Field(min_length=3)
    on_screen_text: str | None = None
    sfx: list[str] = Field(default_factory=list)
    transition: Transition = "cut"
    image_prompt: str = Field(min_length=20)

    @model_validator(mode="after")
    def _timing_sane(self) -> "Scene":
        if self.end <= self.start:
            raise ValueError(f"scene {self.scene}: end must be after start")
        return self

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


class Storyboard(StrictModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str | None = None
    style_bible: StyleBible
    music: MusicCue
    scenes: list[Scene] = Field(min_length=3, max_length=20)

    @field_validator("scenes")
    @classmethod
    def _scenes_are_ordered(cls, scenes: list[Scene]) -> list[Scene]:
        for expected, scene in enumerate(scenes, start=1):
            if scene.scene != expected:
                raise ValueError("scenes must be numbered consecutively from 1")
        return scenes

    @property
    def total_duration(self) -> float:
        return round(max(scene.end for scene in self.scenes), 3)


# ---------------------------------------------------------------------- quality
class QualityScores(StrictModel):
    """Point budget: 100. The maxima mirror the QC rubric in agents/quality_control.md."""

    hook: int = Field(ge=0, le=15)
    originality: int = Field(ge=0, le=10)
    coherence: int = Field(ge=0, le=15)
    suspense: int = Field(ge=0, le=15)
    ending: int = Field(ge=0, le=15)
    voice: int = Field(ge=0, le=10)
    visual_consistency: int = Field(ge=0, le=10)
    subtitle_sync: int = Field(ge=0, le=5)
    audio_mix: int = Field(ge=0, le=5)

    @property
    def total(self) -> int:
        return (
            self.hook
            + self.originality
            + self.coherence
            + self.suspense
            + self.ending
            + self.voice
            + self.visual_consistency
            + self.subtitle_sync
            + self.audio_mix
        )


class QualityReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str
    reviewer: str = Field(min_length=2, max_length=80)
    reviewed_at: datetime = Field(default_factory=utcnow)
    scores: QualityScores
    blocking_issues: list[str] = Field(default_factory=list)
    notes: str | None = None

    @property
    def total(self) -> int:
        return self.scores.total


# -------------------------------------------------------------------- narration
class NarrationBeatTiming(StrictModel):
    beat: int = Field(ge=1)
    text: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    duration: float = Field(gt=0)


class WordTiming(StrictModel):
    word: str = Field(min_length=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    beat: int = Field(ge=1)


class NarrationMetadata(StrictModel):
    """Provenance and timing for one narration track."""

    schema_version: str = SCHEMA_VERSION
    video_id: str
    provider: str
    voice: str
    model_path: str
    license: str
    attribution: str | None = None
    sample_rate: int = Field(gt=0)
    duration: float = Field(gt=0)
    length_scale: float = Field(gt=0)
    alignment_method: str
    created_at: datetime = Field(default_factory=utcnow)
    beats: list[NarrationBeatTiming] = Field(default_factory=list)
    words: list[WordTiming] = Field(default_factory=list)


# --------------------------------------------------------------- technical QC
class TechnicalCheckItem(StrictModel):
    name: str
    passed: bool
    detail: str
    value: str | None = None


class TechnicalReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str
    mp4_path: str
    mp4_sha256: str
    checks: list[TechnicalCheckItem] = Field(default_factory=list)
    passed: bool
    blocking_issues: list[str] = Field(default_factory=list)
    probe: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def failed_checks(self) -> list[TechnicalCheckItem]:
        return [check for check in self.checks if not check.passed]


# --------------------------------------------------------------------- assets
class AssetManifestEntry(StrictModel):
    asset_id: str
    video_id: str | None = None
    kind: str
    path: str
    provider: str | None = None
    source: str
    license: str
    commercial_use: bool = True
    attribution: str | None = None
    sha256: str
    added_at: datetime = Field(default_factory=utcnow)


class AssetManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=utcnow)
    assets: list[AssetManifestEntry] = Field(default_factory=list)


# --------------------------------------------------------------------- render
class SceneRenderTiming(StrictModel):
    scene: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    image: str


class RenderMetadata(StrictModel):
    schema_version: str = SCHEMA_VERSION
    video_id: str
    mp4_path: str
    duration: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    video_codec: str
    audio_codec: str
    subtitle_path: str
    narration_path: str
    mix_path: str
    scene_timings: list[SceneRenderTiming] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "SCHEMA_VERSION",
    "AssetManifest",
    "AssetManifestEntry",
    "Beat",
    "Category",
    "Idea",
    "IdeaScores",
    "IdeaSession",
    "MusicCue",
    "NarrationBeatTiming",
    "NarrationMetadata",
    "QualityReport",
    "QualityScores",
    "RenderMetadata",
    "Scene",
    "SceneRenderTiming",
    "Script",
    "SourceInfo",
    "Storyboard",
    "StyleBible",
    "TechnicalCheckItem",
    "TechnicalReport",
    "Transition",
    "WordTiming",
    "utcnow",
]
