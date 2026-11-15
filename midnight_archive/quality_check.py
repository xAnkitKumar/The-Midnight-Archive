"""Agent 8: final quality gate.

The QC report is scored out of 100 across nine criteria. A video is rejected
if the total is below the configured minimum (default 80) or if any blocking
issue was recorded. The automatic preflight in ``script_editor`` is *not* a
substitute: it cannot assess voice, synchronisation or mixing.
"""

from __future__ import annotations

from dataclasses import dataclass

from midnight_archive.config import Settings
from midnight_archive.models import QualityReport

QC_MAXIMA: dict[str, int] = {
    "hook": 15,
    "originality": 10,
    "coherence": 15,
    "suspense": 15,
    "ending": 15,
    "voice": 10,
    "visual_consistency": 10,
    "subtitle_sync": 5,
    "audio_mix": 5,
}

DEFAULT_MINIMUM = 80


@dataclass(frozen=True)
class QualityDecision:
    total: int
    verdict: str  # "pass" | "fail"
    minimum: int
    failures: list[str]

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


def section_scores(report: QualityReport) -> dict[str, int]:
    return {
        "hook": report.scores.hook,
        "originality": report.scores.originality,
        "coherence": report.scores.coherence,
        "suspense": report.scores.suspense,
        "ending": report.scores.ending,
        "voice": report.scores.voice,
        "visual_consistency": report.scores.visual_consistency,
        "subtitle_sync": report.scores.subtitle_sync,
        "audio_mix": report.scores.audio_mix,
    }


def evaluate(report: QualityReport, settings: Settings) -> QualityDecision:
    minimum = int(settings.get("qc.minimum_total", DEFAULT_MINIMUM))
    require_clean = bool(settings.get("qc.require_no_blocking_issues", True))
    failures: list[str] = []

    if report.total < minimum:
        failures.append(f"Score {report.total}/100 is below the {minimum}/100 gate.")

    if report.blocking_issues:
        if require_clean:
            failures.append(
                f"{len(report.blocking_issues)} blocking issue(s): "
                + "; ".join(report.blocking_issues[:5])
            )

    for name, maximum in QC_MAXIMA.items():
        if name in {"hook", "originality", "coherence", "suspense", "ending"}:
            continue
        if section_scores(report)[name] == 0:
            failures.append(f"Critical section '{name}' scored 0/{maximum}; fix before approval.")

    verdict = "pass" if not failures else "fail"
    return QualityDecision(total=report.total, verdict=verdict, minimum=minimum, failures=failures)


def rubric_rows() -> list[tuple[str, int]]:
    return list(QC_MAXIMA.items())
