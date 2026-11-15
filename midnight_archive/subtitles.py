"""Audio-aligned subtitles.

Whisper word timestamps are obtained **per narration beat**, using the exact
beat audio that was synthesized. Those timestamps are then mapped onto the
script tokens and offset by the beat's measured start time. The total video
duration is never divided equally between sentences.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from midnight_archive.config import Settings
from midnight_archive.errors import ConfigError, PipelineError
from midnight_archive.models import Script
from midnight_archive.voiceover import NarrationPlan, read_wav

_SENTENCE_END = re.compile(r"[.!?][\"'’”)]?$")
_TOKEN_STRIP = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
_PUNCT_ONLY = re.compile(r"^[^\w]+$", re.UNICODE)
_SRT_TIME = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2}),(?P<ms2>\d{3})"
)


@dataclass(frozen=True)
class WordCue:
    word: str
    start: float
    end: float
    beat: int


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SubtitleStyle:
    font_name: str = "Montserrat"
    font_size: int = 58
    margin_v: int = 260
    margin_lr: int = 90
    outline: int = 4
    shadow: float = 1.2
    play_res_x: int = 1080
    play_res_y: int = 1920

    @classmethod
    def from_settings(cls, settings: Settings) -> "SubtitleStyle":
        return cls(
            font_name=str(settings.get("render.subtitle.font_name", "Montserrat")),
            font_size=int(settings.get("render.subtitle.font_size", 58)),
            margin_v=int(settings.get("render.subtitle.margin_v", 260)),
            margin_lr=int(settings.get("render.subtitle.margin_lr", 90)),
            outline=int(settings.get("render.subtitle.outline", 4)),
            shadow=float(settings.get("render.subtitle.shadow", 1.2)),
        )


@dataclass
class SubtitleDocument:
    cues: list[SubtitleCue]
    words: list[WordCue]
    method: str
    warnings: list[str]


# --------------------------------------------------------------------- helpers
def display_tokens(text: str) -> list[str]:
    """Whitespace tokens, merging standalone punctuation into the previous word."""

    tokens: list[str] = []
    for raw in str(text).split():
        if tokens and (_PUNCT_ONLY.match(raw) or raw in {"—", "–", "-"}):
            tokens[-1] = f"{tokens[-1]} {raw}"
        else:
            tokens.append(raw)
    return tokens


def _normalise_token(token: str) -> str:
    token = token.replace("’", "'").lower()
    token = re.sub(r"[^\w'’-]", "", token)
    return token.strip("'-")


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    if source_rate == target_rate:
        return np.asarray(samples, dtype=np.float32)
    if len(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    duration = len(samples) / float(source_rate)
    count = max(1, int(round(len(samples) * target_rate / source_rate)))
    old_axis = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    new_axis = np.linspace(0.0, duration, num=count, endpoint=False)
    return np.interp(new_axis, old_axis, samples).astype(np.float32)


def _weights(tokens: Sequence[str]) -> np.ndarray:
    return np.asarray([max(1.0, len(token) / 4.0) for token in tokens], dtype=np.float64)


def _interpolate_missing(
    timings: list[tuple[float, float] | None],
    tokens: Sequence[str],
    window_start: float,
    window_end: float,
) -> None:
    """Fill unmatched tokens by their relative length inside the surrounding gap."""

    index = 0
    while index < len(timings):
        if timings[index] is not None:
            index += 1
            continue
        end = index
        while end < len(timings) and timings[end] is None:
            end += 1
        before = timings[index - 1][1] if index > 0 and timings[index - 1] else window_start
        after = timings[end][0] if end < len(timings) and timings[end] else window_end
        span = max(0.05, after - before)
        weights = _weights(tokens[index:end])
        total = float(weights.sum()) or 1.0
        cursor = before
        for offset, weight in enumerate(weights):
            duration = span * float(weight) / total
            timings[index + offset] = (cursor, cursor + duration)
            cursor += duration
        index = end


def fallback_beat_tokens(
    tokens: Sequence[str], beat_start: float, beat_duration: float
) -> list[WordCue]:
    """Distribute one beat's words by length inside that beat's measured span.

    This is only used when recognition returns nothing for a beat. It is
    deliberately never used to divide the whole video between sentences.
    """

    weights = _weights(tokens)
    total = float(weights.sum()) or 1.0
    cursor = beat_start
    cues: list[WordCue] = []
    for token, weight in zip(tokens, weights):
        duration = max(0.08, (beat_duration - 0.06) * float(weight) / total)
        cues.append(WordCue(token, round(cursor, 3), round(cursor + duration, 3), 0))
        cursor += duration
    return cues


def align_beat_tokens(
    tokens: Sequence[str],
    recognised: Sequence[tuple[str, float, float]],
    beat_start: float,
    beat_duration: float,
) -> list[WordCue]:
    """Map recognised words onto the authored tokens for one beat.

    Matching is anchored by sequences of equal words. Gaps are distributed by
    token length, not by dividing the whole video or even the whole beat equally.
    """

    if not tokens:
        return []
    if not recognised:
        raise PipelineError("Whisper returned no words for a narration beat")
    source = [_normalise_token(token) for token in tokens]
    target = [_normalise_token(word) for word, _, _ in recognised]
    matcher = difflib.SequenceMatcher(a=source, b=target, autojunk=False)
    timings: list[tuple[float, float] | None] = [None] * len(tokens)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            start, end = recognised[block.b + offset][1], recognised[block.b + offset][2]
            timings[block.a + offset] = (
                beat_start + max(0.0, start),
                beat_start + min(beat_duration, max(start + 0.02, end)),
            )
    _interpolate_missing(timings, tokens, beat_start, beat_start + beat_duration)

    resolved: list[WordCue] = []
    cursor = beat_start
    for token, span in zip(tokens, timings):
        assert span is not None
        start = max(cursor, span[0])
        end = max(start + 0.02, span[1])
        if end > beat_start + beat_duration + 0.35:
            end = beat_start + beat_duration + 0.35
        resolved.append(WordCue(token, round(start, 3), round(end, 3), 0))
        cursor = end
    return resolved


class WhisperAligner:
    """faster-whisper alignment on each beat's exact synthesized audio."""

    def __init__(
        self,
        model_name: str = "base.en",
        compute_type: str = "int8",
        beam_size: int = 5,
    ) -> None:
        self.model_name = model_name
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model = None
        self.warnings: list[str] = []

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ConfigError(
                "faster-whisper is not installed. Run: pip install faster-whisper==1.2.1"
            ) from exc
        try:
            self._model = WhisperModel(
                self.model_name, device="cpu", compute_type=self.compute_type
            )
        except Exception as exc:  # pragma: no cover - model download/runtime
            raise PipelineError(
                f"Could not load faster-whisper model {self.model_name!r}: {exc}"
            ) from exc
        return self._model

    def _recognise(self, samples: np.ndarray, rate: int) -> list[tuple[str, float, float]]:
        model = self._load()
        audio = _resample(samples, rate, 16000)
        try:
            segments, _info = model.transcribe(
                audio,
                language="en",
                beam_size=self.beam_size,
                word_timestamps=True,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            words: list[tuple[str, float, float]] = []
            for segment in segments:
                for word in segment.words or []:
                    text = str(word.word).strip()
                    if text:
                        words.append((text, float(word.start), float(word.end)))
            return words
        except Exception as exc:  # pragma: no cover - runtime
            raise PipelineError(f"Whisper alignment failed: {exc}") from exc

    def align(self, plan: NarrationPlan, script: Script) -> tuple[list[WordCue], str, list[str]]:
        if len(script.narration) != len(plan.beats):
            raise PipelineError("Narration beats do not match the script")
        all_words: list[WordCue] = []
        for script_beat, audio_beat in zip(script.narration, plan.beats):
            tokens = display_tokens(str(script_beat.text))
            recognised = self._recognise(audio_beat.samples, plan.sample_rate)
            duration = max(0.05, audio_beat.end - audio_beat.start)
            try:
                cues = align_beat_tokens(
                    tokens, recognised, audio_beat.start, duration
                )
            except PipelineError:
                # A single failed beat is distributed inside its own exact start
                # and end. The document records that this happened.
                self.warnings.append(
                    f"Beat {script_beat.beat} had no recognised words; timings interpolated "
                    "within the beat."
                )
                cues = fallback_beat_tokens(tokens, audio_beat.start, duration)
            for cue in cues:
                all_words.append(
                    WordCue(cue.word, cue.start, cue.end, int(script_beat.beat))
                )
        method = "faster-whisper word timestamps per beat"
        if len(self.warnings) == len(plan.beats):
            raise PipelineError("Whisper could not align any narration beat")
        if self.warnings:
            method += " + within-beat interpolation"
        return all_words, method, list(self.warnings)


def align_narration(
    plan: NarrationPlan, script: Script, settings: Settings
) -> tuple[list[WordCue], str, list[str]]:
    provider = str(settings.get("audio.aligner.provider", "faster_whisper"))
    if provider != "faster_whisper":
        raise ConfigError(f"Unsupported aligner {provider!r}; use faster_whisper")
    aligner = WhisperAligner(
        model_name=str(settings.get("audio.aligner.model", "base.en")),
        compute_type=str(settings.get("audio.aligner.compute_type", "int8")),
        beam_size=int(settings.get("audio.aligner.beam_size", 5)),
    )
    return aligner.align(plan, script)


# ---------------------------------------------------------------- cue building
def _wrap(text: str, max_line: int = 32) -> str:
    """Wrap to at most two balanced lines, never leaving a one-word second line."""

    words = text.split()
    if not words:
        return text
    if len(text) <= max_line:
        return text
    best: tuple[int, int] | None = None
    for split in range(1, len(words)):
        first = " ".join(words[:split])
        second = " ".join(words[split:])
        if len(first) <= max_line and len(second) <= max_line:
            score = abs(len(first) - len(second))
            if best is None or score < best[0]:
                best = (score, split)
    if best is None:
        # Greedy fallback for unusually long words.
        first, rest = [], list(words)
        while rest and len(" ".join([*first, rest[0]])) <= max_line:
            first.append(rest.pop(0))
        if not first:
            first = [words[0]]
        return "\n".join([" ".join(first), " ".join(rest)])
    return "\n".join([" ".join(words[: best[1]]), " ".join(words[best[1] :])])


def build_cues(
    words: Sequence[WordCue],
    *,
    max_words: int = 7,
    max_chars: int = 54,
    max_line: int = 32,
) -> list[SubtitleCue]:
    if not words:
        return []
    groups: list[list[WordCue]] = []
    current: list[WordCue] = []
    for word in words:
        candidate = " ".join([*(item.word for item in current), word.word])
        boundary = bool(current) and (
            len(current) >= max_words
            or len(candidate) > max_chars
            or (current[-1].beat != word.beat and len(current) >= 2)
            or (
                _SENTENCE_END.search(current[-1].word)
                and len(current) >= 2
            )
            or (current[-1].word.rstrip().endswith(("—", "–")) and len(current) >= 2)
        )
        if boundary:
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)

    cues: list[SubtitleCue] = []
    previous_end = 0.0
    for index, group in enumerate(groups):
        start = max(previous_end, max(0.0, group[0].start - 0.05))
        end = max(start + 0.65, group[-1].end + 0.14)
        if end - start > 5.2:
            end = start + 5.2
        if index + 1 < len(groups):
            next_start = groups[index + 1][0].start
            if next_start - 0.04 < end:
                end = max(start + 0.35, next_start - 0.04)
        cues.append(
            SubtitleCue(
                index=index + 1,
                start=round(start, 3),
                end=round(end, 3),
                text=_wrap(" ".join(word.word for word in group), max_line=max_line),
            )
        )
        previous_end = end
    return cues


def validate_cues(cues: Sequence[SubtitleCue], words: Sequence[WordCue]) -> list[str]:
    issues: list[str] = []
    if not cues:
        return ["No subtitle cues were generated"]
    if any(cue.start < 0 for cue in cues):
        issues.append("A subtitle starts before zero")
    if any(cue.end <= cue.start for cue in cues):
        issues.append("A subtitle has non-positive duration")
    for left, right in zip(cues, cues[1:]):
        if right.start < left.end - 0.02:
            issues.append(f"Subtitles {left.index} and {right.index} overlap")
    strip = lambda value: re.sub(r"\s+", " ", value).strip()
    cue_text = strip(" ".join(cue.text.replace("\n", " ") for cue in cues))
    word_text = strip(" ".join(word.word for word in words))
    if strip(cue_text) != strip(word_text):
        issues.append("Subtitle text does not match the narration words")
    return issues


# ------------------------------------------------------------------- rendering
def format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: Sequence[SubtitleCue], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index}\n{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n"
            f"{cue.text}\n"
        )
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _format_ass_time(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def write_ass(cues: Sequence[SubtitleCue], path: Path, style: SubtitleStyle) -> Path:
    """Write a 1080x1920 ASS stylesheet, so libass never uses its 384x288 default."""

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.play_res_x}
PlayResY: {style.play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Midnight,{style.font_name},{style.font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,{style.outline},{style.shadow},2,{style.margin_lr},{style.margin_lr},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        events.append(
            f"Dialogue: 0,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},"
            f"Midnight,,0,0,0,,{_ass_escape(cue.text)}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return path


def parse_srt(path: Path) -> list[SubtitleCue]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text)
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            index = len(cues) + 1
        match = _SRT_TIME.search(lines[1])
        if not match:
            continue
        start = (
            int(match["h"]) * 3600
            + int(match["m"]) * 60
            + int(match["s"])
            + int(match["ms"]) / 1000
        )
        end = (
            int(match["h2"]) * 3600
            + int(match["m2"]) * 60
            + int(match["s2"])
            + int(match["ms2"]) / 1000
        )
        cues.append(SubtitleCue(index, start, end, "\n".join(lines[2:])))
    return cues


def build_subtitle_document(
    plan: NarrationPlan,
    script: Script,
    settings: Settings,
    srt_path: Path,
    ass_path: Path,
) -> SubtitleDocument:
    words, method, warnings = align_narration(plan, script, settings)
    cues = build_cues(words)
    issues = validate_cues(cues, words)
    if issues:
        raise PipelineError("Subtitle validation failed: " + "; ".join(issues))
    write_srt(cues, srt_path)
    write_ass(cues, ass_path, SubtitleStyle.from_settings(settings))
    return SubtitleDocument(cues=cues, words=words, method=method, warnings=warnings)


def subtitle_text_from_srt(path: Path) -> str:
    return " ".join(cue.text.replace("\n", " ") for cue in parse_srt(path))


def srt_duration(path: Path) -> float:
    cues = parse_srt(path)
    return max((cue.end for cue in cues), default=0.0)


def narration_duration(path: Path) -> float:
    samples, rate, _channels = read_wav(path)
    return len(samples) / float(rate)
