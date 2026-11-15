"""FFmpeg renderer for vertical, subtitled Midnight Archive reels.

The renderer is deliberately story-agnostic. It receives a storyboard, one image
per scene, a narration-aligned ASS file and a mixed stereo WAV; all timing comes
from the storyboard scaled to the audio duration. Nothing here references
TMA-0001.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from midnight_archive.config import Settings
from midnight_archive.doctor import resolve_binary
from midnight_archive.errors import PipelineError
from midnight_archive.models import (
    RenderMetadata,
    Scene,
    SceneRenderTiming,
    Storyboard,
)
from midnight_archive.voiceover import read_wav


@dataclass
class SceneTiming:
    scene: Scene
    start: float
    end: float
    duration: float
    clip_duration: float
    transition_out: float


@dataclass
class RenderResult:
    mp4_path: Path
    metadata: RenderMetadata
    timings: list[SceneTiming]
    stderr_tail: str = ""


_TRANSITION_TYPE = {
    "cut": "fade",
    "match_cut": "fade",
    "fade": "fade",
    "dissolve": "fade",
    "push_in": "smoothup",
    "whip_pan": "slideleft",
}


def _fps_ratio(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            return float(numerator) / float(denominator or 1)
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def scale_scene_timings(storyboard: Storyboard, duration: float, settings: Settings) -> list[SceneTiming]:
    """Scale the storyboard's contiguous scenes onto the measured audio duration."""

    if duration <= 0:
        raise PipelineError("Cannot render a video with non-positive duration")
    source_total = storyboard.total_duration
    if source_total <= 0:
        raise PipelineError("Storyboard has no positive scene end time")
    factor = duration / source_total
    timings: list[SceneTiming] = []
    cursor = 0.0
    for index, scene in enumerate(storyboard.scenes):
        end = duration if index == len(storyboard.scenes) - 1 else round(scene.end * factor, 3)
        if end <= cursor:
            raise PipelineError(f"Scene {scene.scene} has no render time after scaling")
        transition = 0.0
        if index < len(storyboard.scenes) - 1:
            next_scene = storyboard.scenes[index + 1]
            if next_scene.transition in {"fade", "dissolve", "push_in"}:
                transition = float(settings.get("render.transition_seconds", 0.45))
            elif next_scene.transition == "match_cut":
                transition = min(0.30, (end - cursor) * 0.25)
            elif next_scene.transition == "whip_pan":
                transition = 0.35
            else:
                transition = float(settings.get("render.cut_seconds", 0.12))
            transition = min(transition, max(0.05, (end - cursor) * 0.45))
        clip_duration = (end - cursor) + transition
        timings.append(
            SceneTiming(
                scene=scene,
                start=round(cursor, 3),
                end=round(end, 3),
                duration=round(end - cursor, 3),
                clip_duration=round(clip_duration, 3),
                transition_out=transition,
            )
        )
        cursor = end
    return timings


class VideoRenderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        ffmpeg = resolve_binary("ffmpeg")
        ffprobe = resolve_binary("ffprobe")
        if not ffmpeg or not ffprobe:
            raise PipelineError(
                "FFmpeg and ffprobe are required for rendering. Run `doctor` and install them."
            )
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.width = int(settings.get("render.width", 1080))
        self.height = int(settings.get("render.height", 1920))
        self.fps = int(settings.get("render.fps", 30))
        self.crf = int(settings.get("render.crf", 18))
        self.preset = str(settings.get("render.preset", "veryfast"))
        self.zoom = float(settings.get("render.zoom", 0.075))

    # ------------------------------------------------------------------ process
    def _run(self, args: Sequence[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            return subprocess.run(
                list(args),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - long render
            raise PipelineError(f"FFmpeg timed out after {timeout}s") from exc

    def _probe_duration(self, path: Path) -> float:
        result = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            cwd=path.parent,
            timeout=60,
        )
        if result.returncode != 0:
            raise PipelineError(f"ffprobe failed on {path.name}: {result.stderr[-1200:]}")
        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise PipelineError(f"Could not read duration of {path.name}") from exc

    # --------------------------------------------------------------------- render
    def render(
        self,
        video_id: str,
        storyboard: Storyboard,
        image_paths: Sequence[Path],
        subtitle_ass: Path,
        mix_path: Path,
        narration_path: Path,
        output_path: Path,
        *,
        work_dir: Path | None = None,
    ) -> RenderResult:
        if len(image_paths) != len(storyboard.scenes):
            raise PipelineError(
                f"Expected {len(storyboard.scenes)} scene images, got {len(image_paths)}"
            )
        for path in [*image_paths, subtitle_ass, mix_path, narration_path]:
            if not path.is_file():
                raise PipelineError(f"Render input missing: {path}")
        output_path = output_path.resolve()
        if output_path.exists():
            raise PipelineError(
                f"Refusing to overwrite rendered file: {output_path}. Renders are versioned."
            )

        mix_samples, sample_rate, _channels = read_wav(mix_path)
        duration = round(len(mix_samples) / float(sample_rate), 3)
        if duration <= 0:
            raise PipelineError("Mixed audio has no duration")
        timings = scale_scene_timings(storyboard, duration, self.settings)

        work = work_dir or (self.settings.root / "output/drafts" / video_id / "render-tmp")
        if work.exists():
            shutil.rmtree(work)
        (work / "fonts").mkdir(parents=True, exist_ok=True)
        (work / "scenes").mkdir(parents=True, exist_ok=True)

        font_src = self.settings.root / str(
            self.settings.get("render.subtitle.font_file", "assets/fonts/Montserrat-Bold.ttf")
        )
        if not font_src.is_file():
            raise PipelineError(f"Subtitle font missing: {font_src}")
        shutil.copy2(font_src, work / "fonts" / font_src.name)
        shutil.copy2(subtitle_ass, work / "subs.ass")

        scene_files: list[Path] = []
        for index, (scene, source) in enumerate(zip(storyboard.scenes, image_paths), start=1):
            clip_path = work / "scenes" / f"scene-{index:02d}.mp4"
            self._render_scene_clip(
                source,
                clip_path,
                timings[index - 1].clip_duration,
                index,
                work,
            )
            scene_files.append(clip_path)

        graph, last_label = self._xfade_graph(scene_files, timings)
        audio_index = len(scene_files)
        fade_out_start = max(0.0, duration - 0.7)
        graph += (
            f";[{last_label}]ass=subs.ass:fontsdir=fonts,"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out_start:.3f}:d=0.70,"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v]"
        )
        graph += (
            f";[{audio_index}:a]afade=t=in:st=0:d=0.2,"
            f"afade=t=out:st={max(0.0, duration - 0.5):.3f}:d=0.5,"
            f"aresample=48000[a]"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        args: list[str] = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        for path in scene_files:
            args += ["-i", path.name if path.parent == work else str(path)]
        args += ["-i", str(mix_path)]
        args += [
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.fps),
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-max_muxing_queue_size",
            "1024",
            "-t",
            f"{duration:.3f}",
            str(output_path),
        ]
        # The scene inputs live in work/scenes; run FFmpeg from that folder and
        # refer to the ASS/font assets via ../ so no Windows path escaping is needed.
        relative_graph = graph.replace(
            "ass=subs.ass:fontsdir=fonts",
            "ass=../subs.ass:fontsdir=../fonts",
        )
        args[args.index("-filter_complex") + 1] = relative_graph
        result = self._run(args, cwd=work / "scenes", timeout=1200)
        if result.returncode != 0:
            raise PipelineError(
                "FFmpeg render failed:\n" + (result.stderr or result.stdout)[-4000:]
            )
        if not output_path.is_file() or output_path.stat().st_size < 100_000:
            raise PipelineError(f"FFmpeg reported success but output is missing or tiny: {output_path}")

        actual_duration = self._probe_duration(output_path)
        if abs(actual_duration - duration) > 0.20:
            raise PipelineError(
                f"Rendered duration {actual_duration:.3f}s does not match audio {duration:.3f}s"
            )
        scene_metadata = [
            SceneRenderTiming(
                scene=item.scene.scene,
                start=item.start,
                end=item.end,
                image=self.settings.relative(path),
            )
            for item, path in zip(timings, image_paths)
        ]
        metadata = RenderMetadata(
            video_id=video_id,
            mp4_path=self.settings.relative(output_path),
            duration=round(actual_duration, 3),
            width=self.width,
            height=self.height,
            fps=self.fps,
            video_codec="h264",
            audio_codec="aac",
            subtitle_path=self.settings.relative(subtitle_ass),
            narration_path=self.settings.relative(narration_path),
            mix_path=self.settings.relative(mix_path),
            scene_timings=scene_metadata,
        )
        shutil.rmtree(work, ignore_errors=True)
        return RenderResult(
            mp4_path=output_path,
            metadata=metadata,
            timings=timings,
            stderr_tail=(result.stderr or "")[-2000:],
        )

    def _render_scene_clip(
        self,
        image_path: Path,
        clip_path: Path,
        clip_duration: float,
        index: int,
        work: Path,
    ) -> None:
        local_image = work / "scenes" / f"source-{index:02d}.png"
        shutil.copy2(image_path, local_image)
        frames = max(1, round(clip_duration * self.fps))
        rate = self.zoom / max(1, frames)
        if index % 2 == 1:
            zoom_expr = f"min(1+{rate:.8f}*on,{1 + self.zoom:.5f})"
        else:
            zoom_expr = f"max({1 + self.zoom:.5f}-{rate:.8f}*on,1.0)"
        vf = (
            f"scale={self.width * 5 // 4}:{self.height * 5 // 4},"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={self.width}x{self.height}:fps={self.fps},setsar=1,format=yuv420p"
        )
        result = self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(self.fps),
                "-t",
                f"{clip_duration:.3f}",
                "-i",
                local_image.name,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(max(16, self.crf - 1)),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(self.fps),
                "-an",
                clip_path.name,
            ],
            cwd=work / "scenes",
            timeout=300,
        )
        if result.returncode != 0:
            raise PipelineError(
                f"Scene {index} encoding failed:\n{(result.stderr or '')[-3000:]}"
            )

    def _xfade_graph(self, clips: Sequence[Path], timings: Sequence[SceneTiming]) -> tuple[str, str]:
        if not clips:
            raise PipelineError("No scene clips to combine")
        parts: list[str] = []
        last = "0:v"
        offset = 0.0
        for index in range(1, len(clips)):
            previous = timings[index - 1]
            offset += previous.duration
            transition_name = _TRANSITION_TYPE.get(
                timings[index].scene.transition, "fade"
            )
            label = f"x{index}"
            parts.append(
                f"[{last}][{index}:v]xfade=transition={transition_name}:"
                f"duration={previous.transition_out:.3f}:offset={offset:.3f}[{label}]"
            )
            last = label
        return ";".join(parts), last


def probe_rendered(path: Path, ffprobe: str | None = None) -> dict:
    """Small standalone probe used by CLI show/reporting."""

    binary = ffprobe or resolve_binary("ffprobe")
    result = subprocess.run(
        [binary, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise PipelineError(result.stderr[-1200:])
    return json.loads(result.stdout)
