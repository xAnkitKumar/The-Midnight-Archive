from __future__ import annotations

from midnight_archive.config import Settings
from midnight_archive.models import QualityReport
from midnight_archive.quality_check import evaluate

from tests.conftest import quality_payload


def test_full_marks_pass(project: Settings) -> None:
    report = QualityReport.model_validate(quality_payload("TMA-0001", 100))
    decision = evaluate(report, project)
    assert decision.total == 100
    assert decision.verdict == "pass"
    assert decision.failures == []


def test_below_gate_fails(project: Settings) -> None:
    report = QualityReport.model_validate(quality_payload("TMA-0001", 79))
    decision = evaluate(report, project)
    assert decision.total == 79
    assert decision.verdict == "fail"
    assert any("below the 80" in failure for failure in decision.failures)


def test_blocking_issue_fails_even_with_high_score(project: Settings) -> None:
    payload = quality_payload("TMA-0001", 95, blocking=["Subtitle drift of 1.5s in the final scene"])
    report = QualityReport.model_validate(payload)
    decision = evaluate(report, project)
    assert decision.total == 95
    assert decision.verdict == "fail"
    assert any("blocking" in failure for failure in decision.failures)


def test_zero_critical_section_fails(project: Settings) -> None:
    payload = quality_payload("TMA-0001", 95)
    payload["scores"]["audio_mix"] = 0
    report = QualityReport.model_validate(payload)
    decision = evaluate(report, project)
    assert decision.verdict == "fail"
    assert any("audio_mix" in failure for failure in decision.failures)


def test_scores_cannot_exceed_maximum() -> None:
    import pytest
    from pydantic import ValidationError

    payload = quality_payload("TMA-0001", 100)
    payload["scores"]["hook"] = 16
    with pytest.raises(ValidationError):
        QualityReport.model_validate(payload)
