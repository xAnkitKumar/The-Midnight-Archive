from __future__ import annotations
import importlib.util
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location("voice_lab", Path(__file__).resolve().parents[1] / "experiments/voice_lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def test_versioned_runs_and_production_refusal(tmp_path: Path) -> None:
    first = lab.new_run(tmp_path, "piper")
    second = lab.new_run(tmp_path, "piper")
    assert first != second and first.exists() and second.exists()
    for directory in ("data", "output", "assets", "config", "midnight_archive", ".venv"):
        with pytest.raises(ValueError):
            lab.new_run(lab.ROOT / directory / "bad", "piper")


def test_meter_rejects_silence() -> None:
    with pytest.raises(ValueError, match="Invalid/silent"):
        lab.parse_meter(json.dumps({
            "input_i": "-inf", "input_tp": "-inf", "input_lra": "0",
            "input_thresh": "-70", "target_offset": "inf",
        }))
    with pytest.raises(ValueError):
        lab.parse_meter("no JSON")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
def test_real_two_pass_normalization_and_no_overwrite(tmp_path: Path) -> None:
    rate = 24000
    t = np.arange(rate * 12) / rate
    tone = (0.12 * np.sin(2 * np.pi * 180 * t) * (0.65 + 0.35 * np.sin(2 * np.pi * 0.7 * t))).astype(np.float32)
    source = tmp_path / "raw.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((tone * 32767).astype("<i2").tobytes())
    matched = tmp_path / "matched.wav"
    result = lab.normalize(source, matched)
    assert result["passed"]
    stream = lab.probe(matched)["streams"][0]
    assert stream["sample_rate"] == "48000"
    assert stream["channels"] == 1 and stream["bits_per_sample"] == 24
    digest = lab.sha256(matched)
    with pytest.raises(Exception):
        lab.normalize(source, matched)
    assert lab.sha256(matched) == digest


def test_comparison_uses_identical_original_passage() -> None:
    assert " ".join(lab.SENTENCES) == lab.PASSAGE
    assert set(lab.BACKENDS) == {"piper", "chatterbox", "turbo"}
