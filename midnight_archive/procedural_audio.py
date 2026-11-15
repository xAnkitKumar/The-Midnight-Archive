"""Original score, sound effects and the final stereo mix.

Nothing here is sampled from a recording. The bed is synthesized from sine
partials and filtered noise, and the SFX are shaped noise/impulses. They are
registered as original works in the asset manifest.
"""

from __future__ import annotations

import math
import random
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from midnight_archive.config import Settings
from midnight_archive.models import Storyboard
from midnight_archive.voiceover import read_wav, write_wav

SAMPLE_RATE = 48000
SFX_NAMES = (
    "paper_rustle",
    "paper_crease",
    "clock_tick",
    "rain",
    "room_tone",
    "heartbeat",
    "low_boom",
    "switch_click",
    "lift_hum",
    "distant_siren",
    "cello_swell",
    "glass_creak",
)


def _time(duration: float, rate: int = SAMPLE_RATE) -> np.ndarray:
    return np.arange(int(round(duration * rate)), dtype=np.float64) / rate


def _fade(samples: np.ndarray, rate: int, fade_in: float = 0.02, fade_out: float = 0.05) -> np.ndarray:
    n_in = min(len(samples), int(fade_in * rate))
    n_out = min(len(samples), int(fade_out * rate))
    shape = (-1, 1) if samples.ndim == 2 else (-1,)
    if n_in:
        samples[:n_in] *= np.linspace(0.0, 1.0, n_in).reshape(shape)
    if n_out:
        samples[-n_out:] *= np.linspace(1.0, 0.0, n_out).reshape(shape)
    return samples


def _norm(samples: np.ndarray, peak: float = 0.8) -> np.ndarray:
    maximum = float(np.max(np.abs(samples))) if len(samples) else 0.0
    if maximum < 1e-9:
        return samples
    return samples * (peak / maximum)


def _lowpass(samples: np.ndarray, alpha: float) -> np.ndarray:
    """One-pole low-pass in the frequency domain (fast for multi-minute beds)."""

    if len(samples) == 0:
        return samples.astype(np.float32)
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(len(samples))
    response = alpha / (1.0 - (1.0 - alpha) * np.exp(-2j * np.pi * frequencies))
    return np.fft.irfft(spectrum * response, n=len(samples)).real.astype(np.float32)


def _highpass(samples: np.ndarray, alpha: float) -> np.ndarray:
    return samples - _lowpass(samples, alpha)


def _reverb(samples: np.ndarray, rate: int, taps: Sequence[tuple[float, float]]) -> np.ndarray:
    output = samples.copy()
    for delay, gain in taps:
        offset = int(delay * rate)
        if offset <= 0 or offset >= len(samples):
            continue
        output[offset:] += samples[:-offset] * gain
    return output


def _resample(samples: np.ndarray, source_rate: int, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    if source_rate == target_rate or len(samples) == 0:
        return samples.astype(np.float32)
    duration = len(samples) / float(source_rate)
    count = int(round(duration * target_rate))
    old_axis = np.linspace(0.0, duration, len(samples), endpoint=False)
    new_axis = np.linspace(0.0, duration, count, endpoint=False)
    return np.interp(new_axis, old_axis, samples).astype(np.float32)


def _stereo(samples: np.ndarray, width: float = 0.0) -> np.ndarray:
    if samples.ndim == 2:
        return samples.astype(np.float32)
    if width <= 0:
        return np.column_stack([samples, samples]).astype(np.float32)
    delay = int(0.011 * SAMPLE_RATE)
    left = samples
    right = np.concatenate([np.zeros(delay, dtype=samples.dtype), samples[:-delay]])
    return np.column_stack([left, right * (1.0 - width) + samples * width]).astype(np.float32)


# ---------------------------------------------------------------------- score
def generate_score(path: Path, duration: float, *, bpm: int = 66, seed: int = 7) -> Path:
    """Slow D-minor drone with sparse piano-like notes and tape hiss."""

    rate = SAMPLE_RATE
    t = _time(duration)
    rng = np.random.default_rng(seed)
    # D2, A2, F3, C3 - a descending, unresolved loop.
    roots = [73.42, 110.00, 87.31, 65.41]
    chord_tones = [
        [146.83, 174.61, 220.00],
        [220.00, 261.63, 329.63],
        [174.61, 220.00, 261.63],
        [130.81, 164.81, 196.00],
    ]
    bar = 8.0
    left = np.zeros_like(t)
    right = np.zeros_like(t)
    for index in range(int(math.ceil(duration / bar)) + 1):
        chord_index = index % len(roots)
        local = (t >= index * bar) & (t < (index + 1) * bar + 0.6)
        local_t = t[local]
        if not len(local_t):
            continue
        env = np.minimum(1.0, (local_t - index * bar) / 2.2) * np.minimum(
            1.0, ((index + 1) * bar + 0.6 - local_t) / 2.0
        )
        env = np.clip(env, 0.0, 1.0)
        root = roots[chord_index]
        fundamental = np.sin(2 * np.pi * root * local_t) * 0.20
        fifth = np.sin(2 * np.pi * root * 1.5 * local_t + 0.3) * 0.09
        left[local] += (fundamental + fifth) * env
        right[local] += (fundamental * 0.92 + fifth * 1.04) * env
        for tone_index, frequency in enumerate(chord_tones[chord_index]):
            detune = 1.0 + (tone_index - 1) * 0.0018
            slow = 0.55 + 0.45 * np.sin(2 * np.pi * 0.055 * local_t + tone_index)
            pad = (
                np.sin(2 * np.pi * frequency * detune * local_t)
                + 0.28 * np.sin(2 * np.pi * frequency * 2.003 * local_t)
                + 0.12 * np.sin(2 * np.pi * frequency * 3.001 * local_t)
            )
            left[local] += pad * env * slow * 0.035
            right[local] += pad * env * (0.6 + 0.35 * slow) * 0.033
    # A single low piano note every four bars.
    for index in range(0, int(duration // (bar * 2)) + 1):
        start = index * bar * 2 + 1.0
        if start >= duration:
            break
        length = min(7.0, duration - start)
        local_t = _time(length)
        frequency = 146.83 if index % 2 == 0 else 110.0
        note = np.sin(2 * np.pi * frequency * local_t) * np.exp(-local_t * 1.1) * 0.22
        note += np.sin(2 * np.pi * frequency * 2.0 * local_t) * np.exp(-local_t * 2.4) * 0.08
        offset = int(start * rate)
        end = offset + len(note)
        left[offset:end] += note[: len(left[offset:end])]
        right[offset:end] += note[: len(right[offset:end])] * 0.9
    # Tape hiss and low room tone.
    hiss = _highpass(rng.normal(0, 1, len(t)), 0.22) * 0.004
    room = _lowpass(rng.normal(0, 1, len(t)), 0.0015) * 0.055
    left += hiss + room
    right += np.roll(hiss, 37) + np.roll(room, 29)
    left = _reverb(left, rate, [(0.19, 0.16), (0.37, 0.10), (0.71, 0.06)])
    right = _reverb(right, rate, [(0.23, 0.15), (0.41, 0.09), (0.79, 0.05)])
    stereo = np.column_stack([left, right])
    stereo = _fade(stereo, rate, 2.0, min(3.0, duration / 4))
    stereo = _norm(stereo, 0.55)
    write_wav(path, stereo, rate)
    return path


# ------------------------------------------------------------------------ sfx
def _noise_sweep(duration: float, seed: int, low: float, high: float, envelope: str) -> np.ndarray:
    rng = np.random.default_rng(seed)
    count = int(duration * SAMPLE_RATE)
    noise = rng.normal(0, 1, count)
    filtered = _lowpass(noise, high)
    filtered = _highpass(filtered, low)
    if envelope == "swell":
        env = np.sin(np.linspace(0, np.pi, count)) ** 1.5
    elif envelope == "decay":
        env = np.exp(-np.linspace(0, 5, count))
    else:
        env = np.ones(count)
    return filtered * env


def _make_sfx(name: str, duration: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = _time(duration)
    if name in {"paper_rustle", "paper_crease"}:
        sound = _noise_sweep(duration, seed, 0.15, 0.55, "swell")
        if name == "paper_crease":
            sound += np.sin(2 * np.pi * np.linspace(50, 210, len(t))) * np.exp(-t * 8) * 0.18
        return _fade(_norm(sound, 0.55), SAMPLE_RATE, 0.01, 0.08)
    if name == "clock_tick":
        sound = np.zeros_like(t)
        for beat in np.arange(0.2, duration - 0.1, 1.0):
            index = int(beat * SAMPLE_RATE)
            click = np.exp(-np.linspace(0, 50, 900)) * rng.normal(0, 1, 900)
            end = min(len(sound), index + len(click))
            sound[index:end] += click[: end - index] * 0.35
        return _fade(_norm(sound, 0.45), SAMPLE_RATE, 0.005, 0.05)
    if name == "rain":
        sound = _noise_sweep(duration, seed, 0.20, 0.65, "flat") * 0.8
        droplets = np.zeros_like(sound)
        for _ in range(int(duration * 24)):
            position = rng.integers(0, len(droplets) - 2000)
            length = rng.integers(300, 1400)
            droplets[position : position + length] += (
                np.exp(-np.linspace(0, 18, length)) * rng.normal(0, 1, length) * 0.10
            )
        return _fade(_norm(sound + droplets, 0.48), SAMPLE_RATE, 0.4, 0.4)
    if name == "room_tone":
        sound = _lowpass(rng.normal(0, 1, len(t)), 0.0018) * 0.5
        sound += _highpass(rng.normal(0, 1, len(t)), 0.3) * 0.02
        return _fade(_norm(sound, 0.26), SAMPLE_RATE, 0.2, 0.2)
    if name == "heartbeat":
        sound = np.zeros_like(t)
        for start in (0.15, 1.25, 2.35):
            for offset, amplitude in ((0.0, 1.0), (0.22, 0.55)):
                local = t - start - offset
                mask = local >= 0
                sound[mask] += (
                    np.sin(2 * np.pi * 48 * local[mask]) * np.exp(-local[mask] * 18) * amplitude * 0.8
                )
        return _fade(_norm(sound, 0.55), SAMPLE_RATE, 0.005, 0.1)
    if name == "low_boom":
        env = np.exp(-np.linspace(0, 6, len(t)))
        sound = np.sin(2 * np.pi * np.linspace(55, 32, len(t)) * t) * env
        sound += _lowpass(rng.normal(0, 1, len(t)), 0.02) * env * 0.25
        return _fade(_norm(sound, 0.55), SAMPLE_RATE, 0.005, 0.2)
    if name == "switch_click":
        sound = np.zeros_like(t)
        for start in (0.02, 0.12):
            index = int(start * SAMPLE_RATE)
            click = np.exp(-np.linspace(0, 90, 1400)) * rng.normal(0, 1, 1400)
            end = min(len(sound), index + len(click))
            sound[index:end] += click[: end - index]
        return _fade(_norm(sound, 0.45), SAMPLE_RATE, 0.002, 0.02)
    if name == "lift_hum":
        sound = np.sin(2 * np.pi * 58 * t) * 0.22
        sound += np.sin(2 * np.pi * 116 * t + 0.4) * 0.08
        sound += _lowpass(rng.normal(0, 1, len(t)), 0.02) * 0.05
        return _fade(_norm(sound, 0.32), SAMPLE_RATE, 0.2, 0.3)
    if name == "distant_siren":
        sweep = 440 + 55 * np.sin(2 * np.pi * 0.22 * t)
        sound = np.sin(2 * np.pi * np.cumsum(sweep) / SAMPLE_RATE) * 0.16
        sound = _lowpass(sound, 0.035)
        return _fade(_norm(sound, 0.28), SAMPLE_RATE, 0.7, 0.7)
    if name == "cello_swell":
        frequencies = [110.0, 164.81, 220.0]
        sound = sum(np.sin(2 * np.pi * f * t) * 0.07 for f in frequencies)
        sound *= np.sin(np.linspace(0, np.pi, len(t))) ** 1.4
        return _fade(_norm(sound, 0.40), SAMPLE_RATE, 0.4, 0.5)
    if name == "glass_creak":
        sound = _noise_sweep(duration, seed, 0.05, 0.24, "decay")
        sound += np.sin(2 * np.pi * np.linspace(300, 150, len(t))) * np.exp(-t * 3) * 0.08
        return _fade(_norm(sound, 0.34), SAMPLE_RATE, 0.02, 0.2)
    return _fade(_norm(_noise_sweep(duration, seed, 0.1, 0.4, "swell"), 0.3), SAMPLE_RATE, 0.02, 0.1)


def generate_sfx_library(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    durations = {
        "paper_rustle": 1.6,
        "paper_crease": 1.1,
        "clock_tick": 3.2,
        "rain": 6.0,
        "room_tone": 5.0,
        "heartbeat": 3.2,
        "low_boom": 3.0,
        "switch_click": 0.6,
        "lift_hum": 4.0,
        "distant_siren": 4.0,
        "cello_swell": 5.0,
        "glass_creak": 1.8,
    }
    for index, name in enumerate(SFX_NAMES):
        path = output_dir / f"{name}.wav"
        if not path.is_file():
            write_wav(path, _make_sfx(name, durations[name], 500 + index * 31), SAMPLE_RATE)
        paths[name] = path
    return paths


# ------------------------------------------------------------------------ mix
@dataclass
class MixResult:
    duration: float
    peak: float
    music_gain_db: float
    duck_db: float


_SFX_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("paper", "paper_rustle"),
    ("newsprint", "paper_crease"),
    ("page", "paper_crease"),
    ("clock", "clock_tick"),
    ("tick", "clock_tick"),
    ("rain", "rain"),
    ("heart", "heartbeat"),
    ("boom", "low_boom"),
    ("thud", "low_boom"),
    ("click", "switch_click"),
    ("plug", "switch_click"),
    ("switch", "switch_click"),
    ("lift", "lift_hum"),
    ("hum", "lift_hum"),
    ("siren", "distant_siren"),
    ("traffic", "room_tone"),
    ("room tone", "room_tone"),
    ("cello", "cello_swell"),
    ("drone", "cello_swell"),
    ("glass", "glass_creak"),
    ("creak", "glass_creak"),
    ("door", "glass_creak"),
    ("knock", "low_boom"),
    ("bell", "clock_tick"),
)


def _sfx_for_scene(scene, library: Mapping[str, Path]) -> list[Path]:
    selected: list[str] = []
    for cue in scene.sfx:
        lowered = str(cue).lower()
        for keyword, name in _SFX_KEYWORDS:
            if keyword in lowered and name in library and name not in selected:
                selected.append(name)
                break
        if len(selected) >= 2:
            break
    if not selected and scene.scene == 1:
        selected.append("room_tone")
    return [library[name] for name in selected]


def _duck_envelope(narration: np.ndarray, rate: int, duck_db: float) -> np.ndarray:
    """Smoothed music gain that dips while the narrator is speaking."""

    window = max(1, int(0.04 * rate))
    remainder = len(narration) % window
    padded = np.pad(narration, (0, 0 if remainder == 0 else window - remainder))
    power = np.abs(padded).reshape(-1, window).mean(axis=1)
    activity = np.clip(power / 0.035, 0.0, 1.0)
    target = 1.0 - (1.0 - 10 ** (duck_db / 20.0)) * activity
    # Coefficients are per 40 ms frame: duck in ~80 ms, recover in ~350 ms.
    attack = 0.40
    release = 0.11
    gain = np.empty(len(target), dtype=np.float32)
    current = 1.0
    for index, value in enumerate(target):
        coefficient = attack if value < current else release
        current += coefficient * (value - current)
        gain[index] = current
    expanded = np.repeat(gain, window)
    if len(expanded) < len(narration):
        expanded = np.pad(expanded, (0, len(narration) - len(expanded)), mode="edge")
    return expanded[: len(narration)].astype(np.float32)


def mix_audio(
    narration_path: Path,
    music_path: Path,
    sfx_by_scene: Sequence[tuple[float, Sequence[Path]]],
    output_path: Path,
    *,
    duration: float,
    settings: Settings,
) -> MixResult:
    rate = SAMPLE_RATE
    narration, source_rate, _channels = read_wav(narration_path)
    if narration.ndim == 2:
        narration = narration.mean(axis=1)
    narration = _resample(narration, source_rate, rate)
    target_count = int(round(duration * rate))
    if len(narration) < target_count:
        narration = np.pad(narration, (0, target_count - len(narration)))
    narration = narration[:target_count]

    music, music_rate, _ = read_wav(music_path)
    music = _resample(music, music_rate, rate)
    if music.ndim == 1:
        music = _stereo(music)
    if len(music) < target_count:
        repeats = int(np.ceil(target_count / max(1, len(music))))
        music = np.tile(music, (repeats, 1))[:target_count]
    music = music[:target_count]

    music_gain = 10 ** (float(settings.get("audio.music_volume_db", -24.0)) / 20.0)
    duck_db = float(settings.get("audio.duck_db", -10.0))
    duck = _duck_envelope(narration, rate, duck_db)
    music = music * music_gain * duck[:, None]
    # Fade the bed in and out underneath the narration tail.
    fade_in = min(int(1.5 * rate), target_count)
    fade_out = min(int(2.0 * rate), target_count)
    music[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    music[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]

    mix = _stereo(narration, 0.0) + music
    sfx_gain = 10 ** (float(settings.get("audio.sfx_volume_db", -20.0)) / 20.0)
    for start, effects in sfx_by_scene:
        for effect_path in effects:
            effect, effect_rate, _ = read_wav(effect_path)
            if effect.ndim == 2:
                effect = effect.mean(axis=1)
            effect = _resample(effect, effect_rate, rate)
            offset = int(max(0.0, start + 0.10) * rate)
            end = min(target_count, offset + len(effect))
            if end <= offset:
                continue
            segment = effect[: end - offset] * sfx_gain
            mix[offset:end] += np.column_stack([segment, segment])

    # Gentle limiter, then peak normalisation with headroom for AAC.
    peak = float(np.max(np.abs(mix))) if len(mix) else 0.0
    if peak > 0.98:
        mix = np.tanh(mix * 1.15) / np.tanh(1.15)
    mix = _norm(mix, 0.89)
    write_wav(output_path, mix, rate)
    return MixResult(duration=round(target_count / rate, 3), peak=0.89, music_gain_db=music_gain, duck_db=duck_db)


def sfx_plan(storyboard: Storyboard, library: Mapping[str, Path]) -> list[tuple[float, list[Path]]]:
    return [
        (scene.start, _sfx_for_scene(scene, library))
        for scene in storyboard.scenes
    ]
