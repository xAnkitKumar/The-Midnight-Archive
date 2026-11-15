"""Standalone voice audition. Never calls Pipeline, Database, or the renderer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PASSAGE = (
    "At first, I thought the knocking came from next door. "
    "Then I checked the old floor plan. "
    "There was no apartment on the other side of that wall."
)
SENTENCES = (
    "At first, I thought the knocking came from next door.",
    "Then I checked the old floor plan.",
    "There was no apartment on the other side of that wall.",
)
BACKENDS = {
    "piper": ("Public Domain", None),
    "chatterbox": ("MIT", "ResembleAI/chatterbox"),
    "turbo": ("MIT", "ResembleAI/chatterbox-turbo"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_run(base: Path, backend: str) -> Path:
    """Only write to an experimental run tree, never a production artifact tree."""
    base = base.resolve()
    for protected in ("output", "data", "assets", "config", "midnight_archive", ".venv"):
        target = (ROOT / protected).resolve()
        if base == target or target in base.parents:
            raise ValueError(f"Experimental output cannot be inside {target}")
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for version in range(1, 10000):
        run = base / f"{backend}-{stamp}-v{version}"
        try:
            run.mkdir()
            return run
        except FileExistsError:
            continue
    raise RuntimeError("Could not allocate a new run directory")


def ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-n", *args],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def parse_meter(stderr: str) -> dict[str, Any]:
    matches = re.findall(r'\{\s*"input_i".*?\}', stderr, re.DOTALL)
    if not matches:
        raise ValueError("FFmpeg did not return loudness measurements")
    result = json.loads(matches[-1])
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        if not math.isfinite(float(result[key])):
            raise ValueError(f"Invalid/silent audio: {key}={result[key]}")
    return result


def measure(path: Path) -> dict[str, Any]:
    return parse_meter(ffmpeg([
        "-i", str(path), "-af", "loudnorm=I=-23:TP=-3:LRA=11:print_format=json",
        "-f", "null", "-",
    ]).stderr)


def normalize(raw: Path, dest: Path) -> dict[str, Any]:
    before = measure(raw)
    params = (
        "loudnorm=I=-23:TP=-3:LRA=11:linear=true:print_format=json"
        f":measured_I={before['input_i']}:measured_TP={before['input_tp']}"
        f":measured_LRA={before['input_lra']}:measured_thresh={before['input_thresh']}"
        f":offset={before['target_offset']}"
    )
    render = ffmpeg([
        "-i", str(raw), "-af", params, "-ar", "48000", "-ac", "1",
        "-c:a", "pcm_s24le", str(dest),
    ])
    after = measure(dest)
    return {
        "target_integrated_lufs": -23, "true_peak_ceiling_dbtp": -3,
        "before": before, "render": parse_meter(render.stderr), "after": after,
        "passed": abs(float(after["input_i"]) + 23) <= 0.5 and float(after["input_tp"]) <= -2.9,
        "method": "FFmpeg two-pass EBU R128 loudnorm; no time stretching",
    }


def probe(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def synthesize_piper(raw: Path, length_scale: float) -> dict[str, Any]:
    from midnight_archive.config import Settings
    from midnight_archive.models import Beat, Script
    from midnight_archive.voiceover import PiperTTSProvider, write_wav
    settings = Settings.load(ROOT)
    from copy import deepcopy
    raw_settings = deepcopy(settings.raw)
    raw_settings["audio"]["length_scale"] = length_scale
    raw_settings["audio"]["provider"] = "piper"
    raw_settings["audio"]["voice"] = "en_US-ljspeech-high"
    raw_settings["audio"]["mastering"] = {"enabled": False}
    settings = Settings(root=settings.root, raw=raw_settings, brand=settings.brand)
    script = Script(
        title="The Other Side", category="mystery",
        logline="An original short passage for a private voice comparison.",
        narration=[Beat(beat=i, text=s, pause_after_ms=0) for i, s in enumerate(SENTENCES, 1)],
        final_line=SENTENCES[-1],
    )
    provider = PiperTTSProvider(settings)
    started = time.perf_counter()
    plan = provider.synthesize(script)
    elapsed = time.perf_counter() - started
    write_wav(raw, plan.samples, plan.sample_rate)
    return {
        "generation_seconds_including_load": elapsed,
        "parameters": {key: getattr(provider, key) for key in
                       ("length_scale", "noise_scale", "noise_w_scale", "lead_in_ms", "tail_ms")},
        "model_files": {str(provider.voice.model_path): sha256(provider.voice.model_path),
                        str(provider.voice.model_path) + ".json": sha256(Path(str(provider.voice.model_path) + ".json"))},
        "voice": provider.voice.name, "voice_source": provider.voice.source_url,
        "reference": "none; installed single-speaker voice",
        "segmentation": "three production Piper beats, zero extra inter-beat pause",
        "gpu": None,
    }


def synthesize_chatterbox(backend: str, raw: Path, seed: int, revision: str | None, exaggeration: float, temperature: float) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import model_info, snapshot_download
    if os.name == "nt":
        import huggingface_hub.file_download as hf_download
        hf_download.are_symlinks_supported = lambda cache_dir=None: False
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; refusing an unreported CPU fallback")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    repo = BACKENDS[backend][1]
    resolved = revision or model_info(repo).sha
    checkpoint = Path(snapshot_download(
        repo_id=repo, revision=resolved,
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.pt", "*.model", "LICENSE*"],
    ))
    models = {str(p.relative_to(checkpoint)): sha256(p) for p in checkpoint.iterdir() if p.is_file()}
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    start = time.perf_counter()
    if backend == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        model = ChatterboxTurboTTS.from_local(checkpoint, device="cuda")
        params = {"temperature": temperature, "top_p": 0.95, "top_k": 1000, "repetition_penalty": 1.2}
    else:
        from chatterbox.tts import ChatterboxTTS
        model = ChatterboxTTS.from_local(checkpoint, device="cuda")
        params = {"exaggeration": exaggeration, "cfg_weight": 0.5, "temperature": temperature}
    torch.cuda.synchronize()
    loaded = time.perf_counter()
    with torch.inference_mode():
        audio = model.generate(PASSAGE, **params)
    torch.cuda.synchronize()
    finished = time.perf_counter()
    samples = audio.detach().cpu().numpy().reshape(-1)
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError("Model produced empty or nonfinite audio")
    sf.write(str(raw), samples, model.sr, subtype="FLOAT")
    return {
        "repo_id": repo, "revision": resolved, "model_files": models,
        "load_seconds": loaded - start, "generation_seconds": finished - loaded,
        "generation_seconds_including_load": finished - start,
        "parameters": params,
        "reference": "model-distributed conds.pt; no external speaker recording or user voice cloned",
        "segmentation": "continuous three-sentence passage",
        "watermark": "upstream PerTh retained",
        "gpu": {"name": torch.cuda.get_device_name(),
                "total_vram_bytes": torch.cuda.get_device_properties(0).total_memory,
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                "torch_cuda": torch.version.cuda},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "work/voice-lab/runs")
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--exaggeration", type=float, default=0.35, help="Original Chatterbox only; Turbo ignores emotion scaling")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--piper-length-scale", type=float, default=1.25)
    parser.add_argument("--text-file", type=Path, help="Freebuff-finalized excerpt, at least three sentences")
    parser.add_argument("--min-seconds", type=float, default=10)
    parser.add_argument("--max-seconds", type=float, default=15)
    parser.add_argument("--revision", help="Hugging Face commit SHA; recorded even when omitted")
    args = parser.parse_args()
    if not 0 < args.min_seconds <= args.max_seconds or args.piper_length_scale <= 0 or not 0 <= args.exaggeration <= 1 or not 0 < args.temperature <= 2:
        parser.error("Invalid duration range or Piper length scale")
    global PASSAGE, SENTENCES
    if args.text_file:
        PASSAGE = " ".join(args.text_file.read_text(encoding="utf-8-sig").split())
        SENTENCES = tuple(re.split(r"(?<=[.!?])\s+", PASSAGE))
        if len(SENTENCES) < 3:
            parser.error("Provide at least three spoken sentences")
    # Cache is private to this experiment and can be retained for offline replay.
    os.environ.setdefault("HF_HOME", str(ROOT / "work/voice-lab/hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    run = new_run(args.out, args.backend)
    metadata: dict[str, Any] = {
        "schema_version": "1.0", "experimental_only": True, "status": "started",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend, "passage": PASSAGE, "seed": args.seed, "requested_duration_seconds": [args.min_seconds, args.max_seconds],
        "license": BACKENDS[args.backend][0],
        "creative_direction": "Quiet conversational storyteller; restrained unease, no forced bass or horror effects.",
        "python": sys.version, "platform": platform.platform(),
        "packages": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
        "runner_sha256": sha256(Path(__file__)),
        "production_settings_sha256": sha256(ROOT / "config/settings.yaml"),
        "production_voiceover_sha256": sha256(ROOT / "midnight_archive/voiceover.py"),
        "human_review": "pending; machine checks do not assess naturalness or speaker rights",
        "reproducibility": "seed + package versions + model revision/hashes; CUDA bitwise identity is not guaranteed",
    }
    try:
        (run / "passage.txt").write_text(PASSAGE + "\n", encoding="utf-8")
        raw = run / "raw-v1.wav"
        details = synthesize_piper(raw, args.piper_length_scale) if args.backend == "piper" else synthesize_chatterbox(
            args.backend, raw, args.seed, args.revision, args.exaggeration, args.temperature,
        )
        metadata.update(details)
        matched = run / "matched-v1.wav"
        metadata["loudness"] = normalize(raw, matched)
        info = probe(matched)
        duration = float(info["format"]["duration"])
        metadata["duration_seconds"] = duration
        metadata["duration_in_requested_range"] = args.min_seconds <= duration <= args.max_seconds
        metadata["rtf_including_load"] = details["generation_seconds_including_load"] / duration
        if "generation_seconds" in details:
            metadata["rtf_generation"] = details["generation_seconds"] / duration
        metadata["files"] = {
            p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
            for p in (raw, matched)
        }
        metadata["ffprobe"] = info
        metadata["ffmpeg_version"] = subprocess.run(
            ["ffmpeg", "-version"], check=True, capture_output=True, text=True,
        ).stdout.splitlines()[0]
        metadata["status"] = "succeeded" if metadata["loudness"]["passed"] and metadata["duration_in_requested_range"] else "needs_review"
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (run / "metadata-v1.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(json.dumps({"run": str(run), "status": metadata["status"]}), flush=True)
    return 0 if metadata["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
