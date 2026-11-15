"""Generate a versioned full-narration review bundle without advancing the project.

This is deliberately separate from ``Pipeline.narrate``: it does not prepare
assets, mix music/SFX, register artifacts, transition status, render or approve.
It uses the same provider and alignment modules so the reviewed audio is the
production read, not a second voice implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.doctor import resolve_binary
from midnight_archive.models import Script, WordTiming
from midnight_archive.subtitles import build_subtitle_document, display_tokens
from midnight_archive.technical_qc import probe_media, sha256_file
from midnight_archive.utils import utcnow_iso
from midnight_archive.voiceover import (
    build_tts_provider,
    master_narration,
    read_wav,
    voice_info,
    write_wav,
)


def _run(args: Sequence[str], timeout: int = 300) -> subprocess.CompletedProcess:
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


def _loudness(path: Path) -> tuple[float | None, float | None]:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"]
    )
    text = (result.stderr or "") + (result.stdout or "")
    integrated = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", text)
    true_peak = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", text)
    return (
        float(integrated[-1]) if integrated else None,
        float(true_peak[-1]) if true_peak else None,
    )


def _silences(path: Path) -> list[tuple[float, float]]:
    ffmpeg = resolve_binary("ffmpeg")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-45dB:d=0.6",
            "-f",
            "null",
            "-",
        ]
    )
    text = (result.stderr or "") + (result.stdout or "")
    starts = [float(value) for value in re.findall(r"silence_start:\s*(-?[\d.]+)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*(-?[\d.]+)", text)]
    return list(zip(starts, ends))


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    if source_rate == target_rate:
        return np.asarray(samples, dtype=np.float32)
    duration = len(samples) / float(source_rate)
    count = max(1, int(round(len(samples) * target_rate / source_rate)))
    old_axis = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    new_axis = np.linspace(0.0, duration, num=count, endpoint=False)
    return np.interp(new_axis, old_axis, samples).astype(np.float32)


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9:']+", " ", text)
    return text.split()


def _wer(reference: str, hypothesis: str) -> float:
    ref, hyp = _tokens(reference), _tokens(hypothesis)
    table = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=np.int32)
    table[:, 0] = np.arange(len(ref) + 1)
    table[0, :] = np.arange(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            table[i, j] = min(
                table[i - 1, j] + 1,
                table[i, j - 1] + 1,
                table[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]),
            )
    return float(table[-1, -1] / max(len(ref), 1))


def _transcribe(samples: np.ndarray, sample_rate: int, settings: Settings) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(settings.get("audio.aligner.model", "base.en")),
        device="cpu",
        compute_type=str(settings.get("audio.aligner.compute_type", "int8")),
    )
    segments, _info = model.transcribe(
        _resample(samples, sample_rate),
        language="en",
        beam_size=int(settings.get("audio.aligner.beam_size", 5)),
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def _name_probes(out: Path, settings: Settings, info: Any) -> dict[str, Any]:
    from kokoro_onnx import Kokoro

    client = Kokoro(str(info.model_path), str(info.voices_path))
    probes = {
        "elias-voss": "Elias Voss.",
        "mara-kwan": "Mara Kwan.",
        "pair": "Elias Voss knocked on apartment 4A. Mara Kwan lived there.",
    }
    directory = out / "pronunciation-probes"
    directory.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for name, text in probes.items():
        samples, rate = client.create(
            text,
            voice=info.name,
            speed=info.speed,
            lang=str(settings.get("audio.language", "en-gb")),
        )
        audio = master_narration(np.asarray(samples, dtype=np.float32), int(rate), settings)
        path = directory / f"{name}.wav"
        write_wav(path, audio, int(rate))
        transcript = _transcribe(audio, int(rate), settings)
        tokens = _tokens(transcript)
        results[name] = {
            "text": text,
            "path": path.as_posix(),
            "sha256": sha256_file(path),
            "seconds": round(len(audio) / int(rate), 3),
            "transcript": transcript,
            "tokens": tokens,
            "elias": "elias" in tokens,
            "voss": "voss" in tokens,
            "mara": "mara" in tokens,
            "kwan": "kwan" in tokens,
            "suspicious": [token for token in tokens if token in {"lara", "eliza", "quam", "vass", "kwon"}],
        }
    (directory / "probes-v1.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default="TMA-0001")
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/narration_review/TMA-0001-v3-bm_george"),
    )
    args = parser.parse_args()

    settings = Settings.load()
    db = Database(settings.db_path)
    video = db.require_video(args.video)
    if not video["script_json"] or not video["storyboard_json"]:
        raise SystemExit(f"{args.video} has no script/storyboard")
    script = Script.model_validate(json.loads(str(video["script_json"])))
    script_version = 3
    script_path = settings.root / (
        "output/scripts/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v3.json"
    )
    if not script_path.is_file():
        raise SystemExit(f"v3 script artifact missing: {script_path}")

    out = args.out / f"v{args.version}"
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to overwrite existing review folder: {out}")
    out.mkdir(parents=True, exist_ok=True)

    before_status = str(video["status"])
    info = voice_info(settings)
    provider = build_tts_provider(settings)
    plan = provider.synthesize(script)
    # The 800 ms production tail is not speech. Remove only unused trailing
    # near-silence when it would push this review past the 60 s requirement.
    trailing_trimmed = 0.0
    if plan.duration > 60.0:
        trim_seconds = min(0.5, plan.duration - 59.8)
        trim_samples = int(round(trim_seconds * plan.sample_rate))
        tail = np.asarray(plan.samples[-trim_samples:], dtype=np.float32)
        if trim_samples > 0 and float(np.max(np.abs(tail))) < 1e-4:
            plan.samples = plan.samples[:-trim_samples]
            trailing_trimmed = trim_seconds

    narration_path = out / "narration.wav"
    srt_path = out / "subtitles.srt"
    ass_path = out / "subtitles.ass"
    write_wav(narration_path, plan.samples, plan.sample_rate)
    document = build_subtitle_document(plan, script, settings, srt_path, ass_path)

    words = [
        WordTiming(word=item.word, start=item.start, end=item.end, beat=item.beat)
        for item in document.words
    ]
    metadata = plan.metadata(
        args.video,
        length_scale=float(plan.voice.speed),
        words=words,
        alignment_method=document.method,
    ).model_dump(mode="json")
    metadata["created_at"] = utcnow_iso()
    metadata["script_version"] = script_version
    metadata["script_sha256"] = sha256_file(script_path)
    metadata["review_only"] = True
    (out / "narration-metadata-v1.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "alignment-v1.json").write_text(
        json.dumps(
            {
                "method": document.method,
                "warnings": document.warnings,
                "word_count": len(document.words),
                "words": [
                    {"word": word.word, "start": word.start, "end": word.end, "beat": word.beat}
                    for word in document.words
                ],
                "cues": [
                    {"index": cue.index, "start": cue.start, "end": cue.end, "text": cue.text}
                    for cue in document.cues
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    mono, sample_rate, channels = read_wav(narration_path)
    mono = mono.mean(axis=1) if mono.ndim == 2 else mono
    duration = len(mono) / sample_rate
    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2))) if len(mono) else 0.0
    clipping = int(np.count_nonzero(np.abs(mono) >= 0.999))
    silences = _silences(narration_path)
    lufs, true_peak = _loudness(narration_path)
    probe = probe_media(narration_path)
    transcript = _transcribe(mono, sample_rate, settings)
    token_set = set(_tokens(transcript))
    names = {
        "elias": "elias" in token_set,
        "voss": "voss" in token_set,
        "mara": "mara" in token_set,
        "kwan": "kwan" in token_set,
        "suspicious": sorted(
            token for token in token_set if token in {"lara", "eliza", "quam", "vass", "kwon"}
        ),
    }
    probes = _name_probes(out, settings, info)

    subtitle_text = " ".join(cue.text.replace("\n", " ") for cue in document.cues)
    subtitle_span = max((cue.end for cue in document.cues), default=0.0)
    qc = {
        "schema_version": "1.0",
        "video_id": args.video,
        "script_version": script_version,
        "review_only": True,
        "created_at": utcnow_iso(),
        "status_before": before_status,
        "status_after": str(db.require_video(args.video)["status"]),
        "narrator": {
            "provider": plan.provider,
            "voice": plan.voice.name,
            "language": settings.get("audio.language"),
            "speed": plan.voice.speed,
            "license": plan.voice.license,
            "model": settings.relative(plan.voice.model_path),
        },
        "audio": {
            "path": narration_path.as_posix(),
            "trailing_silence_trimmed_s": round(trailing_trimmed, 3),
            "sha256": sha256_file(narration_path),
            "seconds": round(duration, 3),
            "sample_rate": sample_rate,
            "channels": channels,
            "peak_dbfs": round(20 * np.log10(max(peak, 1e-9)), 2),
            "rms_dbfs": round(20 * np.log10(max(rms, 1e-9)), 2),
            "integrated_lufs": lufs,
            "true_peak_dbfs": true_peak,
            "clipping_samples": clipping,
            "silence_over_0_6s": len(silences),
            "longest_silence_s": round(max((end - start for start, end in silences), default=0.0), 3),
            "probe": probe,
        },
        "alignment": {
            "method": document.method,
            "warnings": document.warnings,
            "words": len(document.words),
            "script_words": script.word_count,
            "cues": len(document.cues),
            "subtitle_span": round(subtitle_span, 3),
            "coverage_ratio": round(subtitle_span / duration, 3) if duration else None,
            "text_matches_script": _tokens(subtitle_text) == _tokens(script.plain_text),
        },
        "asr": {
            "transcript": transcript,
            "wer": round(_wer(script.plain_text, transcript), 3),
            "names": names,
            "note": "base.en ASR is a machine check, not a listening test.",
        },
        "pronunciation_probes": probes,
        "checks": {
            "duration_45_to_60": 45.0 <= duration <= 60.0,
            "no_clipping": clipping == 0,
            "peak_below_minus_1_dbfs": peak <= 10 ** (-1.0 / 20.0),
            "subtitles_present": bool(document.cues),
            "subtitle_text_matches_script": _tokens(subtitle_text) == _tokens(script.plain_text),
            "word_count_matches": len(document.words) == script.word_count,
            "status_unchanged": before_status == str(db.require_video(args.video)["status"]),
            "names_detected_in_full_read": all(
                names[key] for key in ("elias", "mara", "kwan")
            ),
        },
    }
    qc["passed"] = all(qc["checks"].values())
    (out / "audio-qc-v1.json").write_text(
        json.dumps(qc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    readme = f"""# TMA-0001 v3 full narration review — {plan.voice.name}

**Review only. Project status before and after: `{before_status}`. No asset stage,\n    render, approval or publication was performed.**

## Selected voice

- Kokoro-82M `{plan.voice.name}`, `{settings.get('audio.language')}`, speed {plan.voice.speed}
- Licence: {plan.voice.license}; runtime: `kokoro-onnx` MIT
- Audition: `output/voice_tests/v2/level-matched/kokoro-bm_george-reference.wav`
- Selection record: `output/voice_selection/TMA-0001-narrator-v3.json`

## Full read

- Audio: `{narration_path.name}` — {duration:.3f} s, {sample_rate} Hz, {channels} channel(s)
- Subtitles: `subtitles.srt`, `subtitles.ass`
- Alignment: {len(document.words)} words, {len(document.cues)} cues, method “{document.method}”
- Peak: {qc['audio']['peak_dbfs']} dBFS; integrated: {lufs} LUFS; true peak: {true_peak} dBTP
- Trailing near-silence trimmed for this review: {trailing_trimmed:.3f} s; clipping samples: {clipping}; silences over 0.6 s: {len(silences)}
- Duration inside 45–60 s: {qc['checks']['duration_45_to_60']}
- Subtitle text matches script: {qc['checks']['subtitle_text_matches_script']}
- Word count matches: {qc['checks']['word_count_matches']}

## Pronunciation check

The full-read ASR heard Elias/Mara/Kwan: {names}. Isolated probes are in\n    `pronunciation-probes/`. This is a machine check, not a human listening judgment.\n    Check `elias-voss.wav`, `mara-kwan.wav`, `pair.wav`, and the full read for the\n    names, 4A/4B and 3:07.

## Decision

Listen to the full read before any further production stage. Do not render the\n    video until explicitly authorized.
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(qc, indent=2))
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
