"""Agent 3: script validation and editorial preflight.

Two different things live here:

``validate_script``
    Hard gates (word count, duration, banned phrasing, source compliance).
    A script with errors is rejected and never stored.

``preflight``
    A transparent, automatic score out of 100 for *script craft only*. It is a
    first pass, not the final QC: it cannot hear narration or see the video.
    The final 80/100 gate is applied later by ``quality_check``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from midnight_archive.config import Settings
from midnight_archive.models import Script
from midnight_archive.utils import count_words

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_QUESTION = re.compile(r"\?")
_PAUSE_MARKERS = re.compile(r"(\.\.\.|—|--|;)")

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    message: str


@dataclass(frozen=True)
class ScriptMetrics:
    word_count: int
    estimated_duration: float
    beat_count: int
    hook_words: int
    sentence_count: int
    average_sentence_words: float
    longest_sentence_words: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "word_count": self.word_count,
            "estimated_duration_seconds": self.estimated_duration,
            "beat_count": self.beat_count,
            "hook_words": self.hook_words,
            "sentence_count": self.sentence_count,
            "average_sentence_words": self.average_sentence_words,
            "longest_sentence_words": self.longest_sentence_words,
        }


@dataclass(frozen=True)
class PreflightResult:
    score: int
    breakdown: dict[str, int]
    notes: list[str] = field(default_factory=list)


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]


def estimate_duration(script: Script, settings: Settings) -> float:
    """Seconds of narration at the configured reading speed, plus scripted pauses."""

    words_per_second = float(settings.get("script.words_per_second", 2.5))
    if words_per_second <= 0:  # pragma: no cover - guarded by config
        words_per_second = 2.5
    pause_seconds = sum(beat.pause_after_ms for beat in script.narration) / 1000.0
    return round(script.word_count / words_per_second + pause_seconds, 2)


def metrics(script: Script, settings: Settings) -> ScriptMetrics:
    all_sentences = sentences(script.plain_text)
    lengths = [count_words(sentence) for sentence in all_sentences] or [0]
    return ScriptMetrics(
        word_count=script.word_count,
        estimated_duration=estimate_duration(script, settings),
        beat_count=len(script.narration),
        hook_words=count_words(script.narration[0].text),
        sentence_count=len(all_sentences),
        average_sentence_words=round(sum(lengths) / len(lengths), 1),
        longest_sentence_words=max(lengths),
    )


def _phrase_hits(text: str, phrases: list[str]) -> list[str]:
    lowered = text.casefold()
    return [phrase for phrase in phrases if phrase.casefold() in lowered]


def validate_script(script: Script, settings: Settings) -> list[Issue]:
    """Return every editorial and technical issue, ordered errors first."""

    issues: list[Issue] = []
    word_count = script.word_count
    duration = estimate_duration(script, settings)

    min_words = int(settings.get("script.min_words", 90))
    max_words = int(settings.get("script.max_words", 130))
    if word_count < min_words:
        issues.append(
            Issue(
                "error",
                "script.too_short",
                f"{word_count} words is below the {min_words}-word minimum; the video would feel thin.",
            )
        )
    if word_count > max_words:
        issues.append(
            Issue(
                "error",
                "script.too_long",
                f"{word_count} words exceeds the {max_words}-word limit; cut lines, do not speed up delivery.",
            )
        )

    min_seconds = float(settings.get("script.min_duration_seconds", 35))
    max_seconds = float(settings.get("script.max_duration_seconds", 60))
    if duration < min_seconds:
        issues.append(
            Issue(
                "error",
                "script.duration_short",
                f"Estimated narration is {duration:.1f}s, below the {min_seconds:.0f}s minimum.",
            )
        )
    if duration > max_seconds:
        issues.append(
            Issue(
                "error",
                "script.duration_long",
                f"Estimated narration is {duration:.1f}s, above the {max_seconds:.0f}s maximum.",
            )
        )

    if len(script.narration) < 3:  # pragma: no cover - model enforces
        issues.append(Issue("error", "script.too_few_beats", "A story needs at least three beats."))

    max_hook_words = int(settings.get("script.max_hook_words", 12))
    hook_words = count_words(script.narration[0].text)
    if hook_words > max_hook_words:
        issues.append(
            Issue(
                "warning",
                "script.slow_hook",
                f"The opening line is {hook_words} words; the impossible detail may land after two seconds.",
            )
        )

    banned = _phrase_hits(script.plain_text, list(settings.get("script.banned_phrases", [])))
    if banned:
        issues.append(
            Issue(
                "error",
                "script.banned_phrase",
                "Banned cliché(s) present: " + "; ".join(banned),
            )
        )
    weak = _phrase_hits(script.plain_text, list(settings.get("script.weak_phrases", [])))
    if weak:
        issues.append(
            Issue(
                "warning",
                "script.weak_phrase",
                "Replace weak phrasing: " + "; ".join(weak),
            )
        )

    max_sentence_words = int(settings.get("script.max_sentence_words", 22))
    long_sentences = [s for s in sentences(script.plain_text) if count_words(s) > max_sentence_words]
    if long_sentences:
        issues.append(
            Issue(
                "warning",
                "script.long_sentence",
                f"{len(long_sentences)} sentence(s) exceed {max_sentence_words} words; narration will drag.",
            )
        )

    exclamations = script.plain_text.count("!")
    if exclamations > 3:
        issues.append(
            Issue(
                "warning",
                "script.shouty",
                f"{exclamations} exclamation marks undermine the controlled, intimate tone.",
            )
        )

    beat_texts = [beat.text.casefold().strip(" .!?") for beat in script.narration]
    duplicates = {text for text in beat_texts if beat_texts.count(text) > 1}
    if duplicates:
        issues.append(
            Issue("warning", "script.repeated_beat", "A narration line is repeated verbatim.")
        )

    words = set(re.findall(r"[a-z']+", script.plain_text.casefold()))
    first_person = len(words & {"i", "me", "my", "mine", "we", "our"})
    third_person = len(words & {"he", "she", "they", "him", "her", "them", "his", "hers"})
    if first_person > 0 and third_person > 0:
        issues.append(
            Issue(
                "warning",
                "script.pov_shift",
                "Both first-person and third-person narration appear; keep one point of view.",
            )
        )

    final_words = count_words(script.narration[-1].text)
    if final_words > 18:
        issues.append(
            Issue(
                "warning",
                "script.long_ending",
                f"The final line is {final_words} words; a memorable last line usually lands in under 12.",
            )
        )

    if script.source.type == "public_domain_adaptation" and not script.source.reference:
        issues.append(
            Issue("error", "script.source_missing", "An adaptation must record its source work.")
        )

    issues.sort(key=lambda item: _LEVEL_ORDER[item.level])
    return issues


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.level == "error"]


def preflight(script: Script, settings: Settings) -> PreflightResult:
    """Automatic script-craft score out of 100 (not the final QC)."""

    data = metrics(script, settings)
    issues = validate_script(script, settings)
    notes: list[str] = []

    # Hook (30): the impossible detail must land fast.
    if data.hook_words <= 7:
        hook_score = 30
    elif data.hook_words <= 9:
        hook_score = 26
    elif data.hook_words <= 12:
        hook_score = 20
    elif data.hook_words <= 16:
        hook_score = 12
    else:
        hook_score = 6

    # Pacing (25): long sentences and repeated lines cost points.
    pacing_score = 25
    pacing_score -= 3 * len([s for s in sentences(script.plain_text) if count_words(s) > 22])
    pacing_score -= 2 * len({b.text for b in script.narration if [x.text for x in script.narration].count(b.text) > 1})
    pacing_score = max(0, pacing_score)

    # Suspense (20): short beats, unanswered questions, beat pauses.
    short_beats = len([b for b in script.narration if count_words(b.text) <= 6])
    suspense_score = min(12, short_beats * 2)
    if _QUESTION.search(script.plain_text):
        suspense_score += 4
    if _PAUSE_MARKERS.search(script.plain_text):
        suspense_score += 2
    suspense_score += 2 if any(beat.pause_after_ms > 0 for beat in script.narration) else 0
    suspense_score = min(20, suspense_score)

    # Ending (15): a short, declarative final line.
    final_words = count_words(script.narration[-1].text)
    if final_words <= 8:
        ending_score = 15
    elif final_words <= 12:
        ending_score = 12
    elif final_words <= 16:
        ending_score = 8
    else:
        ending_score = 4

    # Compliance (10): no banned phrasing.
    warnings = [issue for issue in issues if issue.level == "warning"]
    errors = [issue for issue in issues if issue.level == "error"]
    compliance_score = 10 if not errors else 0
    compliance_score -= min(4, len(warnings))
    compliance_score = max(0, compliance_score)

    breakdown = {
        "hook": hook_score,
        "pacing": pacing_score,
        "suspense": suspense_score,
        "ending": ending_score,
        "compliance": compliance_score,
    }
    total = sum(breakdown.values())

    notes.append(
        f"{data.word_count} words, ~{data.estimated_duration:.1f}s, {data.beat_count} beats, "
        f"{data.sentence_count} sentences (avg {data.average_sentence_words} words)."
    )
    for issue in issues:
        notes.append(f"{issue.level.upper()} [{issue.code}] {issue.message}")

    return PreflightResult(score=int(total), breakdown=breakdown, notes=notes)


def format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"
