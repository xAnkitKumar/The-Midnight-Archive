"""Local narration with a replaceable provider interface.

Kokoro-82M is the default provider (Apache-2.0 weights, MIT ONNX runtime); Piper
remains an available GPL-3.0 fallback. Each voice model has a separate licence
that must be declared in ``config/settings.yaml`` before this module will
synthesise anything. No paid API is used.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from midnight_archive.config import Settings
from midnight_archive.errors import ConfigError, PipelineError
from midnight_archive.licensing import require_commercial_license
from midnight_archive.models import NarrationMetadata, Script, WordTiming
from midnight_archive.utils import utcnow_iso

SAMPLE_WIDTH_BYTES = 2


@dataclass(frozen=True)
class VoiceInfo:
    name: str
    provider: str
    model_path: Path
    license: str
    commercial_use: bool
    source_url: str
    attribution: str
    config_path: Path | None = None
    voices_path: Path | None = None
    speed: float = 1.0


@dataclass
class BeatAudio:
    beat: int
    text: str
    start: float
    end: float
    samples: np.ndarray = field(repr=False)


@dataclass
class NarrationPlan:
    provider: str
    voice: VoiceInfo
    sample_rate: int
    samples: np.ndarray = field(repr=False)
    beats: list[BeatAudio]

    @property
    def duration(self) -> float:
        return round(len(self.samples) / self.sample_rate, 3)

    def metadata(
        self,
        video_id: str,
        *,
        length_scale: float,
        words: list[WordTiming],
        alignment_method: str,
    ) -> NarrationMetadata:
        return NarrationMetadata(
            video_id=video_id,
            provider=self.provider,
            voice=self.voice.name,
            model_path=self.voice.model_path.as_posix(),
            license=self.voice.license,
            attribution=self.voice.attribution,
            sample_rate=self.sample_rate,
            duration=self.duration,
            length_scale=length_scale,
            alignment_method=alignment_method,
            beats=[
                {
                    "beat": beat.beat,
                    "text": beat.text,
                    "start": round(beat.start, 3),
                    "end": round(beat.end, 3),
                    "duration": round(beat.end - beat.start, 3),
                }
                for beat in self.beats
            ],
            words=words,
        )


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def synthesize(self, script: Script) -> NarrationPlan:  # pragma: no cover - protocol
        ...


def default_voice_name(settings: Settings, provider: str) -> str | None:
    """Find the first configured voice for a provider (stable config order)."""

    configured = settings.get("audio.voices", {})
    if isinstance(configured, dict):
        for name, item in configured.items():
            if not isinstance(item, dict):
                continue
            item_provider = str(
                item.get("provider", settings.get("audio.provider", "piper"))
            ).lower()
            if item_provider == provider:
                return str(name)
    return None


def voice_info(settings: Settings, voice_name: str | None = None) -> VoiceInfo:
    """Load and validate the voice's *separate* commercial licence."""

    name = voice_name or str(settings.get("audio.voice", "en_US-ljspeech-high"))
    configured = settings.get(f"audio.voices.{name}")
    if not isinstance(configured, dict):
        raise ConfigError(
            f"Voice {name!r} is not declared under audio.voices. Its model licence "
            "must be recorded before narration can be generated."
        )
    if not configured.get("commercial_use", False):
        raise ConfigError(f"Voice {name!r} is not cleared for commercial use")
    license_name = str(configured.get("license", ""))
    require_commercial_license(license_name, what=f"Voice {name!r}")

    provider = str(
        configured.get("provider", settings.get("audio.provider", "piper"))
    ).lower()
    if provider == "piper":
        model_rel = str(configured.get("model") or f"audio/voice_dir/{name}.onnx")
        model_path = settings.root / model_rel
        if not model_path.is_file():
            raise ConfigError(
                f"Voice model not found: {model_path}. Download the ONNX model and its "
                ".onnx.json config, then place them under assets/voices/."
            )
        config_path = model_path.with_suffix(model_path.suffix + ".json")
        if not config_path.is_file():
            raise ConfigError(f"Voice config not found: {config_path}")
        voices_path = None
    elif provider == "kokoro":
        model_rel = str(configured.get("model", ""))
        voices_rel = str(configured.get("voices", ""))
        if not model_rel or not voices_rel:
            raise ConfigError(
                f"Kokoro voice {name!r} must declare both model and voices paths."
            )
        model_path = settings.root / model_rel
        voices_path = settings.root / voices_rel
        if not model_path.is_file():
            raise ConfigError(f"Kokoro model not found: {model_path}")
        if not voices_path.is_file():
            raise ConfigError(f"Kokoro voices pack not found: {voices_path}")
        config_path = None
    else:
        raise ConfigError(
            f"Unsupported TTS provider {provider!r} for voice {name!r}. "
            "Supported: piper, kokoro."
        )

    return VoiceInfo(
        name=name,
        provider=provider,
        model_path=model_path,
        license=license_name,
        commercial_use=True,
        source_url=str(configured.get("source_url", "")),
        attribution=str(configured.get("attribution", "")),
        config_path=config_path,
        voices_path=voices_path,
        speed=float(configured.get("speed", settings.get("audio.speed", 1.0))),
    )


def _moving_average(samples: np.ndarray, window: int) -> np.ndarray:
    """Fast centred moving average with edge padding, same length as input."""

    if window <= 1 or len(samples) == 0:
        return np.asarray(samples, dtype=np.float32)
    window = window | 1
    pad = window // 2
    padded = np.pad(np.asarray(samples, dtype=np.float64), (pad, pad), mode="edge")
    cumulative = np.cumsum(np.insert(padded, 0, 0.0))
    averaged = (cumulative[window:] - cumulative[:-window]) / window
    return averaged[: len(samples)].astype(np.float32)


def master_narration(samples: np.ndarray, sample_rate: int, settings: Settings) -> np.ndarray:
    """Gentle broadcast-style cleanup that preserves length and beat timings.

    The chain removes DC/rumble, evens out close-mic level differences with a
    slow 1.8:1 compressor, and normalises peak to -1.5 dBFS. It deliberately does
    not add artificial reverb, pitch shift or dramatic EQ.
    """

    audio = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
    if len(audio) == 0 or not bool(settings.get("audio.mastering.enabled", True)):
        return audio
    audio -= float(np.mean(audio))
    cutoff = max(20.0, float(settings.get("audio.mastering.highpass_hz", 70.0)))
    window = max(3, int(round(0.44 * sample_rate / cutoff)))
    audio -= _moving_average(audio, window)

    threshold_db = float(settings.get("audio.mastering.threshold_db", -20.0))
    ratio = max(1.0, float(settings.get("audio.mastering.ratio", 1.8)))
    threshold = 10 ** (threshold_db / 20.0)
    envelope = _moving_average(np.abs(audio), max(3, int(0.012 * sample_rate)))
    gain = np.ones_like(envelope, dtype=np.float32)
    above = envelope > threshold
    gain[above] = (threshold + (envelope[above] - threshold) / ratio) / envelope[above]
    audio *= gain

    target_db = float(settings.get("audio.mastering.target_peak_db", -1.5))
    target = 10 ** (target_db / 20.0)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 1e-9:
        audio *= target / peak
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


class PiperTTSProvider:
    """Piper provider. Each beat is synthesized separately so pauses are exact."""

    name = "piper"

    def __init__(self, settings: Settings, voice_name: str | None = None) -> None:
        self.settings = settings
        self.voice = voice_info(settings, voice_name or default_voice_name(settings, "piper"))
        self.length_scale = float(settings.get("audio.length_scale", 1.0))
        self.noise_scale = float(settings.get("audio.noise_scale", 0.667))
        self.noise_w_scale = float(settings.get("audio.noise_w_scale", 0.8))
        self.lead_in_ms = int(settings.get("audio.lead_in_ms", 250))
        self.tail_ms = int(settings.get("audio.tail_ms", 700))
        self._voice = None

    def _load(self):
        if self._voice is not None:
            return self._voice
        try:
            from piper import PiperVoice, SynthesisConfig  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ConfigError(
                "piper-tts is not installed. Run: pip install piper-tts==1.8.0"
            ) from exc
        try:
            self._voice = PiperVoice.load(str(self.voice.model_path))
        except Exception as exc:  # pragma: no cover - depends on model files
            raise PipelineError(f"Could not load Piper voice {self.voice.model_path}: {exc}") from exc
        self._synthesis_config = SynthesisConfig(
            length_scale=self.length_scale,
            noise_scale=self.noise_scale,
            noise_w_scale=self.noise_w_scale,
            normalize_audio=True,
        )
        return self._voice

    def synthesize(self, script: Script) -> NarrationPlan:
        voice = self._load()
        if self.length_scale <= 0:
            raise ConfigError("audio.length_scale must be greater than zero")

        sample_rate: int | None = None
        chunks: list[np.ndarray] = []
        beat_audio: list[BeatAudio] = []
        cursor = 0.0

        lead = np.zeros(int(round(self.lead_in_ms / 1000 * 22050)), dtype=np.float32)
        # The real sample rate is known from the first chunk; the lead is rebuilt
        # after synthesis so it matches the model exactly.

        for beat in script.narration:
            try:
                pieces = list(
                    voice.synthesize(str(beat.text), syn_config=self._synthesis_config)
                )
            except Exception as exc:  # pragma: no cover - depends on model
                raise PipelineError(f"Piper failed on beat {beat.beat}: {exc}") from exc
            arrays = [
                np.asarray(piece.audio_float_array, dtype=np.float32).reshape(-1)
                for piece in pieces
                if len(piece.audio_float_array)
            ]
            if not arrays:
                raise PipelineError(
                    f"Piper returned no audio for beat {beat.beat}: {beat.text!r}"
                )
            if sample_rate is None:
                sample_rate = int(pieces[0].sample_rate)
                lead = np.zeros(int(round(self.lead_in_ms / 1000 * sample_rate)), dtype=np.float32)
            for piece in pieces[1:]:
                if int(piece.sample_rate) != sample_rate:
                    raise PipelineError("Piper returned inconsistent sample rates")
            audio = np.concatenate(arrays).astype(np.float32, copy=False)
            # Short edge fades prevent clicks when chunks are concatenated.
            fade = min(int(0.006 * sample_rate), len(audio) // 2)
            if fade:
                audio[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
                audio[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)

            start = cursor
            chunks.append(
                lead
                if beat.beat == script.narration[0].beat
                else np.zeros(0, dtype=np.float32)
            )
            chunks.append(audio)
            cursor += len(audio)
            end = cursor
            beat_audio.append(
                BeatAudio(
                    beat=beat.beat,
                    text=str(beat.text),
                    start=round(start / sample_rate, 3),
                    end=round(end / sample_rate, 3),
                    samples=audio,
                )
            )
            pause_ms = int(getattr(beat, "pause_after_ms", 0) or 0)
            if pause_ms > 0:
                silence = np.zeros(int(round(pause_ms / 1000 * sample_rate)), dtype=np.float32)
                chunks.append(silence)
                cursor += len(silence)

        if sample_rate is None:
            raise PipelineError("Piper produced no audio")
        tail = np.zeros(int(round(self.tail_ms / 1000 * sample_rate)), dtype=np.float32)
        chunks.append(tail)
        full = np.concatenate([chunk for chunk in chunks if len(chunk)]).astype(np.float32)
        full = master_narration(full, sample_rate, self.settings)
        # Recompute beat offsets because the lead-in is inserted before beat one.
        lead_seconds = lead.size / sample_rate
        for item in beat_audio:
            item.start = round(item.start + lead_seconds, 3)
            item.end = round(item.end + lead_seconds, 3)
        return NarrationPlan(
            provider=self.name,
            voice=self.voice,
            sample_rate=sample_rate,
            samples=full,
            beats=beat_audio,
        )


class KokoroTTSProvider:
    """Kokoro-82M ONNX provider with a warm, conversational default voice."""

    name = "kokoro"

    def __init__(self, settings: Settings, voice_name: str | None = None) -> None:
        self.settings = settings
        self.voice = voice_info(settings, voice_name or default_voice_name(settings, "kokoro"))
        if self.voice.provider != "kokoro":  # pragma: no cover - guarded by build_tts_provider
            raise ConfigError(f"Voice {self.voice.name!r} is not a Kokoro voice")
        self.speed = float(self.voice.speed)
        self.length_scale = self.speed
        self.language = str(self.settings.get("audio.language", "en-us"))
        self.lead_in_ms = int(self.settings.get("audio.lead_in_ms", 250))
        self.tail_ms = int(self.settings.get("audio.tail_ms", 800))
        self._client = None

    def _load(self):
        if self._client is not None:
            return self._client
        try:
            from kokoro_onnx import Kokoro  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - environment
            raise ConfigError(
                "kokoro-onnx is not installed. Run: uv pip install kokoro-onnx==0.6.1"
            ) from exc
        if self.voice.voices_path is None:  # pragma: no cover - voice_info enforces
            raise ConfigError("Kokoro voices pack path is missing")
        try:
            self._client = Kokoro(
                str(self.voice.model_path), str(self.voice.voices_path)
            )
        except Exception as exc:  # pragma: no cover - model/runtime
            raise PipelineError(f"Could not load Kokoro voice {self.voice.name}: {exc}") from exc
        return self._client

    def synthesize(self, script: Script) -> NarrationPlan:
        client = self._load()
        sample_rate: int | None = None
        chunks: list[np.ndarray] = []
        beat_audio: list[BeatAudio] = []
        cursor = 0.0
        lead = np.zeros(0, dtype=np.float32)

        for beat in script.narration:
            try:
                samples, rate = client.create(
                    str(beat.text),
                    voice=self.voice.name,
                    speed=self.speed,
                    lang=self.language,
                )
            except Exception as exc:  # pragma: no cover - model/runtime
                raise PipelineError(f"Kokoro failed on beat {beat.beat}: {exc}") from exc
            audio = np.asarray(samples, dtype=np.float32).reshape(-1)
            if len(audio) == 0:
                raise PipelineError(f"Kokoro returned no audio for beat {beat.beat}")
            if sample_rate is None:
                sample_rate = int(rate)
                lead = np.zeros(
                    int(round(self.lead_in_ms / 1000 * sample_rate)), dtype=np.float32
                )
            elif int(rate) != sample_rate:  # pragma: no cover - runtime
                raise PipelineError("Kokoro returned inconsistent sample rates")
            fade = min(int(0.006 * sample_rate), len(audio) // 2)
            if fade:
                audio[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
                audio[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            chunks.append(lead if beat.beat == script.narration[0].beat else np.zeros(0, dtype=np.float32))
            chunks.append(audio)
            start = cursor
            cursor += len(audio)
            beat_audio.append(
                BeatAudio(
                    beat=beat.beat,
                    text=str(beat.text),
                    start=round(start / sample_rate, 3),
                    end=round(cursor / sample_rate, 3),
                    samples=audio,
                )
            )
            pause_ms = int(getattr(beat, "pause_after_ms", 0) or 0)
            if pause_ms > 0:
                silence = np.zeros(int(round(pause_ms / 1000 * sample_rate)), dtype=np.float32)
                chunks.append(silence)
                cursor += len(silence)

        if sample_rate is None:
            raise PipelineError("Kokoro produced no audio")
        tail = np.zeros(int(round(self.tail_ms / 1000 * sample_rate)), dtype=np.float32)
        chunks.append(tail)
        full = np.concatenate([chunk for chunk in chunks if len(chunk)]).astype(np.float32)
        full = master_narration(full, sample_rate, self.settings)
        lead_seconds = lead.size / sample_rate
        for item in beat_audio:
            item.start = round(item.start + lead_seconds, 3)
            item.end = round(item.end + lead_seconds, 3)
        return NarrationPlan(
            provider=self.name,
            voice=self.voice,
            sample_rate=sample_rate,
            samples=full,
            beats=beat_audio,
        )


def build_tts_provider(settings: Settings, voice_name: str | None = None) -> TTSProvider:
    info = voice_info(settings, voice_name)
    if info.provider == "piper":
        return PiperTTSProvider(settings, info.name)
    if info.provider == "kokoro":
        return KokoroTTSProvider(settings, info.name)
    raise ConfigError(
        f"Unsupported TTS provider {info.provider!r}. Supported: piper, kokoro."
    )


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> Path:
    """Write mono or interleaved stereo float audio as 16-bit PCM WAV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1:
        channels = 1
        interleaved = data
    elif data.ndim == 2:
        channels = int(data.shape[1])
        interleaved = data.reshape(-1)
    else:  # pragma: no cover - programmer error
        raise ValueError("samples must be 1-D or 2-D")
    pcm = (np.clip(interleaved, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(SAMPLE_WIDTH_BYTES)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int, int]:
    """Read a 16-bit PCM WAV as float32 with shape ``(frames, channels)``."""

    if not path.is_file():
        raise PipelineError(f"Audio file not found: {path}")
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != SAMPLE_WIDTH_BYTES:
        raise PipelineError(f"Only 16-bit PCM WAV is supported: {path}")
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels)
    return pcm, rate, channels


def audio_sha_metadata(plan: NarrationPlan, video_id: str, *, length_scale: float,
                       words: list[WordTiming], alignment_method: str) -> dict:
    """Serialisable metadata with a stable creation timestamp for artifacts."""

    payload = plan.metadata(
        video_id,
        length_scale=length_scale,
        words=words,
        alignment_method=alignment_method,
    ).model_dump(mode="json")
    payload["created_at"] = utcnow_iso()
    return payload
