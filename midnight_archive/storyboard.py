"""Agent 4 validation: storyboard coverage, timing and continuity.

A storyboard is only useful if it can be cut to the narration. These checks
enforce that every spoken word appears in exactly one scene, that scenes tile
the timeline without gaps or overlaps, and that the total length matches the
script's estimated duration.
"""

from __future__ import annotations

from dataclasses import dataclass

from midnight_archive.config import Settings
from midnight_archive.models import Script, Storyboard
from midnight_archive.script_editor import Issue, estimate_duration
from midnight_archive.utils import normalize_words


@dataclass(frozen=True)
class StoryboardMetrics:
    scene_count: int
    total_duration: float
    average_scene_seconds: float
    shortest_scene: float
    longest_scene: float
    estimated_script_duration: float


def metrics(storyboard: Storyboard, script: Script, settings: Settings) -> StoryboardMetrics:
    durations = [scene.duration for scene in storyboard.scenes]
    return StoryboardMetrics(
        scene_count=len(storyboard.scenes),
        total_duration=storyboard.total_duration,
        average_scene_seconds=round(sum(durations) / len(durations), 2),
        shortest_scene=min(durations),
        longest_scene=max(durations),
        estimated_script_duration=estimate_duration(script, settings),
    )


def _first_divergence(expected: list[str], actual: list[str]) -> tuple[int, str, str]:
    limit = min(len(expected), len(actual))
    for index in range(limit):
        if expected[index] != actual[index]:
            start = max(0, index - 6)
            return (
                index,
                " ".join(expected[start : index + 6]),
                " ".join(actual[start : index + 6]),
            )
    index = limit
    start = max(0, index - 6)
    return (
        index,
        " ".join(expected[start : index + 6]) or "(nothing)",
        " ".join(actual[start : index + 6]) or "(nothing)",
    )


def validate_storyboard(
    storyboard: Storyboard, script: Script, settings: Settings
) -> list[Issue]:
    issues: list[Issue] = []
    scenes = storyboard.scenes
    if not scenes:  # pragma: no cover - model enforces
        return [Issue("error", "storyboard.empty", "The storyboard has no scenes.")]

    tolerance = 0.05
    if scenes[0].start > tolerance:
        issues.append(
            Issue(
                "error",
                "storyboard.late_start",
                f"The first scene starts at {scenes[0].start:.2f}s; it must start at 0.",
            )
        )

    for previous, current in zip(scenes, scenes[1:]):
        drift = current.start - previous.end
        if abs(drift) > tolerance:
            kind = "gap" if drift > 0 else "overlap"
            issues.append(
                Issue(
                    "error",
                    "storyboard.timing_break",
                    f"Scene {current.scene} starts at {current.start:.2f}s but scene {previous.scene} "
                    f"ends at {previous.end:.2f}s ({kind} of {abs(drift):.2f}s).",
                )
            )
        if current.scene != previous.scene + 1:  # pragma: no cover - model enforces
            issues.append(
                Issue(
                    "error",
                    "storyboard.scene_numbering",
                    f"Scene numbering jumps from {previous.scene} to {current.scene}.",
                )
            )

    min_scene = float(settings.get("storyboard.min_scene_seconds", 1.2))
    max_scene = float(settings.get("storyboard.max_scene_seconds", 12))
    for scene in scenes:
        if scene.duration < min_scene:
            issues.append(
                Issue(
                    "warning",
                    "storyboard.scene_too_short",
                    f"Scene {scene.scene} lasts {scene.duration:.2f}s; below {min_scene:.1f}s "
                    "it cannot be read on screen.",
                )
            )
        if scene.duration > max_scene:
            issues.append(
                Issue(
                    "warning",
                    "storyboard.scene_too_long",
                    f"Scene {scene.scene} lasts {scene.duration:.2f}s; above {max_scene:.1f}s "
                    "a static image stops holding attention.",
                )
            )

    expected_words = normalize_words(script.plain_text)
    actual_words = normalize_words(" ".join(scene.narration for scene in scenes))
    if expected_words != actual_words:
        position, expected_context, actual_context = _first_divergence(expected_words, actual_words)
        issues.append(
            Issue(
                "error",
                "storyboard.narration_mismatch",
                f"Scene narration diverges from the script at word {position + 1}. "
                f"Script: '{expected_context}'. Storyboard: '{actual_context}'.",
            )
        )

    min_seconds = float(settings.get("script.min_duration_seconds", 35))
    max_seconds = float(settings.get("script.max_duration_seconds", 60))
    if storyboard.total_duration < min_seconds:
        issues.append(
            Issue(
                "error",
                "storyboard.too_short",
                f"The storyboard runs {storyboard.total_duration:.1f}s, below the {min_seconds:.0f}s minimum.",
            )
        )
    if storyboard.total_duration > max_seconds:
        issues.append(
            Issue(
                "error",
                "storyboard.too_long",
                f"The storyboard runs {storyboard.total_duration:.1f}s, above the {max_seconds:.0f}s maximum.",
            )
        )

    min_scenes = int(settings.get("storyboard.min_scenes", 4))
    max_scenes = int(settings.get("storyboard.max_scenes", 14))
    if len(scenes) < min_scenes:
        issues.append(
            Issue(
                "warning",
                "storyboard.few_scenes",
                f"{len(scenes)} scenes for a {storyboard.total_duration:.0f}s video; aim for at least {min_scenes}.",
            )
        )
    if len(scenes) > max_scenes:
        issues.append(
            Issue(
                "warning",
                "storyboard.many_scenes",
                f"{len(scenes)} scenes exceeds the {max_scenes}-scene guideline; the edit will feel frantic.",
            )
        )

    estimated = estimate_duration(script, settings)
    tolerance_ratio = float(settings.get("storyboard.duration_tolerance", 0.10))
    if estimated > 0 and abs(storyboard.total_duration - estimated) > estimated * tolerance_ratio:
        issues.append(
            Issue(
                "warning",
                "storyboard.duration_drift",
                f"Storyboard is {storyboard.total_duration:.1f}s but the narration estimate is "
                f"{estimated:.1f}s (>{tolerance_ratio:.0%} difference). Re-time scenes to the voice track.",
            )
        )

    if not any(scene.sfx for scene in scenes):
        issues.append(
            Issue(
                "warning",
                "storyboard.no_sfx",
                "No scene lists a sound effect; the mix will feel flat between music beats.",
            )
        )

    if not any(scene.on_screen_text for scene in scenes):
        issues.append(
            Issue(
                "warning",
                "storyboard.no_on_screen_text",
                "No scene uses on-screen text; title cards and key clues can raise retention.",
            )
        )

    issues.sort(key=lambda item: 0 if item.level == "error" else 1)
    return issues


def summary(storyboard: Storyboard) -> str:
    return (
        f"{len(storyboard.scenes)} scenes, {storyboard.total_duration:.1f}s, "
        f"music '{storyboard.music.mood}' at {storyboard.music.bpm} BPM"
    )
