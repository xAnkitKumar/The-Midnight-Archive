"""Technical inspection of the actual MP4.

This module answers only one question: is the file valid, playable and within
the delivery specification? Creative judgement lives in the separate quality
report and is never inferred from a technically valid render.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

from midnight_archive.config import Settings
from midnight_archive.doctor import resolve_binary
from midnight_archive.errors import PipelineError
from midnight_archive.models import (
    NarrationMetadata,
    RenderMetadata,
    Script,
    TechnicalCheckItem,
    TechnicalReport,
)
from midnight_archive.subtitles import display_tokens, parse_srt


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: Sequence[str], timeout: int = 180) -> subprocess.CompletedProcess:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags,
    )


def probe_media(path: Path) -> dict[str, Any]:
    binary = resolve_binary("ffprobe")
    result = _run(
        [
            binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=90,
    )
    if result.returncode != 0:
        raise PipelineError(f"ffprobe could not read {path.name}: {result.stderr[-1500:]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid ffprobe output for {path.name}") from exc


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fps(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        if "/" in value:
            left, right = value.split("/", 1)
            return float(left) / float(right or 1)
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _first(streams: Sequence[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((stream for stream in streams if stream.get("codec_type") == kind), None)


def _volumedetect(path: Path) -> tuple[float | None, float | None]:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        timeout=180,
    )
    text = (result.stderr or "") + (result.stdout or "")
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", text)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", text)
    return (
        float(mean.group(1)) if mean else None,
        float(peak.group(1)) if peak else None,
    )


def _black_segments(path: Path, duration: float) -> list[tuple[float, float]]:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.6:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=180,
    )
    text = (result.stderr or "") + (result.stdout or "")
    starts = [float(value) for value in re.findall(r"black_start:([\d.]+)", text)]
    ends = [float(value) for value in re.findall(r"black_end:([\d.]+)", text)]
    return list(zip(starts, ends))


def _silence_segments(path: Path, duration: float) -> list[tuple[float, float]]:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-45dB:d=1.0",
            "-vn",
            "-f",
            "null",
            "-",
        ],
        timeout=180,
    )
    text = (result.stderr or "") + (result.stdout or "")
    starts = [float(value) for value in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*(-?[\d.]+)", text)]
    return list(zip(starts, ends))


def _integrated_loudness(path: Path) -> float | None:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        timeout=180,
    )
    text = (result.stderr or "") + (result.stdout or "")
    matches = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", text)
    return float(matches[-1]) if matches else None


def _check(name: str, passed: bool, detail: str, value: str | None = None) -> TechnicalCheckItem:
    return TechnicalCheckItem(name=name, passed=bool(passed), detail=detail, value=value)


def run_technical_qc(
    video_id: str,
    mp4_path: Path,
    srt_path: Path,
    narration: NarrationMetadata,
    script: Script,
    render: RenderMetadata,
    settings: Settings,
    *,
    expected_scene_count: int | None = None,
) -> TechnicalReport:
    mp4_path = mp4_path.resolve()
    checks: list[TechnicalCheckItem] = []
    if not mp4_path.is_file():
        missing = _check("file_exists", False, f"MP4 missing: {mp4_path}")
        return TechnicalReport(
            video_id=video_id,
            mp4_path=settings.relative(mp4_path),
            mp4_sha256="",
            checks=[missing],
            passed=False,
            blocking_issues=[missing.detail],
        )
    size = mp4_path.stat().st_size
    checks.append(_check("file_exists", True, f"Found {mp4_path.name}", f"{size} bytes"))
    checks.append(_check("file_size", size >= 500_000, f"{size / 1_000_000:.2f} MB", str(size)))

    probe = probe_media(mp4_path)
    format_info = probe.get("format", {})
    streams = probe.get("streams", [])
    video = _first(streams, "video")
    audio = _first(streams, "audio")
    duration = _as_float(format_info.get("duration"))
    if video is None:
        checks.append(_check("video_stream", False, "No video stream"))
        return TechnicalReport(
            video_id=video_id,
            mp4_path=settings.relative(mp4_path),
            mp4_sha256=sha256_file(mp4_path),
            checks=checks,
            passed=False,
            blocking_issues=["No video stream"],
            probe={"duration": duration},
        )
    checks.append(_check("video_stream", True, "One video stream present"))
    checks.append(_check("video_codec", video.get("codec_name") == "h264", str(video.get("codec_name"))))
    checks.append(
        _check(
            "resolution",
            int(video.get("width", 0)) == int(settings.get("render.width", 1080))
            and int(video.get("height", 0)) == int(settings.get("render.height", 1920)),
            f"{video.get('width')}x{video.get('height')}",
            f"{video.get('width')}x{video.get('height')}",
        )
    )
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    ratio = width / height if height else 0.0
    checks.append(
        _check(
            "aspect_ratio",
            abs(ratio - 9 / 16) < 0.002,
            f"{ratio:.5f} (target 0.5625)",
            f"{ratio:.5f}",
        )
    )
    fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    checks.append(
        _check("frame_rate", abs(fps - float(settings.get("render.fps", 30))) < 0.02, f"{fps:.3f} fps", f"{fps:.3f}")
    )
    checks.append(_check("pixel_format", video.get("pix_fmt") == "yuv420p", str(video.get("pix_fmt"))))
    checks.append(
        _check("duration_limit", 0 < duration <= 60.0, f"{duration:.3f} s (Instagram Reel limit 60 s)", f"{duration:.3f}")
    )
    checks.append(
        _check(
            "duration_matches_audio",
            abs(duration - narration.duration) <= 0.25,
            f"video {duration:.3f}s vs narration {narration.duration:.3f}s",
        )
    )
    expected_scenes = expected_scene_count
    scene_count = len(render.scene_timings)
    scene_ok = bool(render.scene_timings)
    if scene_ok:
        scene_ok = (
            scene_count >= 3
            and abs(render.scene_timings[0].start) < 0.02
            and abs(render.scene_timings[-1].end - duration) <= 0.25
        )
    checks.append(
        _check(
            "scene_timing",
            scene_ok,
            (
                f"{scene_count} scenes, "
                f"{render.scene_timings[0].start:.2f}s–{render.scene_timings[-1].end:.2f}s"
                if render.scene_timings
                else "No scene timings in render metadata"
            ),
            str(scene_count),
        )
    )
    if expected_scenes:
        checks.append(
            _check(
                "expected_scene_count",
                scene_count == int(expected_scenes),
                f"{scene_count} rendered scenes (expected {expected_scenes})",
                str(scene_count),
            )
        )

    if audio is None:
        checks.append(_check("audio_stream", False, "No audio stream"))
    else:
        checks.append(_check("audio_stream", True, "One audio stream present"))
        checks.append(_check("audio_codec", audio.get("codec_name") == "aac", str(audio.get("codec_name"))))
        checks.append(
            _check(
                "audio_sample_rate",
                int(audio.get("sample_rate", 0)) == 48000,
                f"{audio.get('sample_rate')} Hz",
                str(audio.get("sample_rate")),
            )
        )
        audio_duration = _as_float(audio.get("duration"))
        checks.append(
            _check(
                "audio_duration",
                audio_duration > 0 and abs(audio_duration - duration) <= 0.25,
                f"audio {audio_duration:.3f}s vs container {duration:.3f}s",
            )
        )

    mean_volume, max_volume = _volumedetect(mp4_path)
    checks.append(
        _check(
            "peak_level",
            max_volume is not None and -20.0 <= max_volume <= -0.2,
            f"max {max_volume} dBFS",
            f"{max_volume}",
        )
    )
    checks.append(
        _check(
            "mean_level",
            mean_volume is not None and -32.0 <= mean_volume <= -8.0,
            f"mean {mean_volume} dBFS",
            f"{mean_volume}",
        )
    )
    loudness = _integrated_loudness(mp4_path)
    checks.append(
        _check(
            "integrated_loudness",
            loudness is not None and -24.0 <= loudness <= -9.0,
            f"{loudness} LUFS (target about -14)",
            f"{loudness}",
        )
    )

    blacks = _black_segments(mp4_path, duration)
    unexpected_black = [
        (start, end)
        for start, end in blacks
        if start > 1.2 and end < duration - 1.2 and (end - start) >= 0.6
    ]
    checks.append(
        _check(
            "black_frames",
            not unexpected_black,
            "No unexpected black intervals"
            if not unexpected_black
            else f"Black intervals: {unexpected_black}",
            str(len(blacks)),
        )
    )
    silences = _silence_segments(mp4_path, duration)
    unexpected_silence = [
        (start, end)
        for start, end in silences
        if start > 1.5 and end < duration - 1.5 and (end - start) >= 1.0
    ]
    checks.append(
        _check(
            "silent_sections",
            not unexpected_silence,
            "No unexpected silent sections"
            if not unexpected_silence
            else f"Silences: {unexpected_silence}",
            str(len(silences)),
        )
    )

    cues = parse_srt(srt_path)
    checks.append(_check("subtitles_present", bool(cues), f"{len(cues)} cues"))
    if cues:
        first_start = min(cue.start for cue in cues)
        last_end = max(cue.end for cue in cues)
        checks.append(
            _check(
                "subtitle_start",
                0.0 <= first_start <= 2.0,
                f"first cue at {first_start:.2f}s",
                f"{first_start:.3f}",
            )
        )
        checks.append(
            _check(
                "subtitle_end",
                0.0 < last_end <= duration + 0.05,
                f"last cue ends {last_end:.2f}s / video {duration:.2f}s",
                f"{last_end:.3f}",
            )
        )
        checks.append(
            _check(
                "subtitle_tail",
                duration - last_end >= 0.2,
                f"{duration - last_end:.2f}s after last subtitle",
            )
        )
        ordered = all(
            right.start >= left.end - 0.03 for left, right in zip(cues, cues[1:])
        )
        checks.append(_check("subtitle_order", ordered, "Cues are monotonic with no overlap"))
        sane_durations = all(0.25 <= cue.end - cue.start <= 5.5 for cue in cues)
        checks.append(_check("subtitle_cue_duration", sane_durations, "All cue durations are 0.25–5.5 s"))
        srt_words = " ".join(cue.text.replace("\n", " ") for cue in cues)
        expected_words = " ".join(beat.text for beat in script.narration)
        checks.append(
            _check(
                "subtitle_text",
                " ".join(srt_words.split()) == " ".join(expected_words.split()),
                f"{len(display_tokens(srt_words))} subtitle words vs {script.word_count} script words",
                str(len(display_tokens(srt_words))),
            )
        )
        checks.append(
            _check(
                "subtitle_narration_coverage",
                last_end >= narration.duration - 1.6,
                f"last subtitle {last_end:.2f}s, narration {narration.duration:.2f}s",
            )
        )

    checks.append(
        _check(
            "narration_not_cut",
            narration.duration <= duration + 0.05,
            f"narration {narration.duration:.3f}s within video {duration:.3f}s",
        )
    )

    ffmpeg = resolve_binary("ffmpeg")
    integrity = _run(
        [ffmpeg, "-v", "error", "-i", str(mp4_path), "-f", "null", "-"], timeout=240
    )
    checks.append(
        _check(
            "file_integrity",
            integrity.returncode == 0 and not (integrity.stderr or "").strip(),
            "Full decode completed without errors"
            if integrity.returncode == 0
            else (integrity.stderr or "Decode failed")[-600:],
        )
    )

    passed = all(check.passed for check in checks)
    blocking = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
    return TechnicalReport(
        video_id=video_id,
        mp4_path=settings.relative(mp4_path),
        mp4_sha256=sha256_file(mp4_path),
        checks=checks,
        passed=passed,
        blocking_issues=blocking,
        probe={
            "format_name": str(format_info.get("format_name", "")),
            "duration": round(duration, 3),
            "size": size,
            "video_codec": str(video.get("codec_name", "")),
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "audio_codec": str((audio or {}).get("codec_name", "")),
            "sample_rate": int((audio or {}).get("sample_rate", 0) or 0) if audio else 0,
            "mean_volume_db": mean_volume,
            "max_volume_db": max_volume,
            "integrated_loudness": loudness,
        },
    )
