from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from midnight_archive.asset_manager import AssetManager
from midnight_archive.config import Settings
from midnight_archive.database import Database
from midnight_archive.errors import ConfigError
from midnight_archive.models import (
    Beat,
    NarrationBeatTiming,
    NarrationMetadata,
    Script,
    Storyboard,
    WordTiming,
)
from midnight_archive.procedural_audio import _duck_envelope, generate_score, mix_audio
from midnight_archive.renderer import VideoRenderer, scale_scene_timings
from midnight_archive.subtitles import (
    SubtitleCue,
    SubtitleStyle,
    WordCue,
    align_beat_tokens,
    build_cues,
    parse_srt,
    validate_cues,
    write_ass,
    write_srt,
)
from midnight_archive.technical_qc import probe_media, run_technical_qc
from midnight_archive.voiceover import (
    KokoroTTSProvider,
    PiperTTSProvider,
    master_narration,
    read_wav,
    voice_info,
    write_wav,
)
from midnight_archive.visuals import generate_still

REPO_ROOT = Path(__file__).resolve().parents[1]


def _short_script() -> Script:
    return Script(
        title="The Empty Corridor",
        category="mystery",
        logline="A short script used only to exercise the local voice path.",
        narration=[
            Beat(beat=1, text="The corridor was empty.", pause_after_ms=0),
            Beat(beat=2, text="A door opened.", pause_after_ms=0),
            Beat(beat=3, text="Nobody was there.", pause_after_ms=0),
        ],
        final_line="Nobody was there.",
    )


def _short_storyboard() -> Storyboard:
    payload = json.loads((REPO_ROOT / "samples/demo_storyboard.json").read_text(encoding="utf-8"))
    scenes = payload["scenes"][:3]
    scenes[0].update({"start": 0.0, "end": 1.6, "transition": "cut"})
    scenes[1].update({"start": 1.6, "end": 3.0, "transition": "fade"})
    scenes[2].update({"start": 3.0, "end": 4.5, "transition": "fade"})
    payload["scenes"] = scenes
    return Storyboard.model_validate(payload)


def test_piper_produces_beat_timed_wav(repo_settings: Settings) -> None:
    pytest.importorskip("piper")
    if not repo_settings.path("assets/voices/en_US-ljspeech-high.onnx").is_file():
        pytest.skip("Piper voice model is not installed on this machine")
    script = _short_script()
    plan = PiperTTSProvider(repo_settings).synthesize(script)
    assert plan.provider == "piper"
    assert plan.voice.license.lower() == "public domain"
    assert plan.sample_rate == 22050
    assert plan.duration > 2.0
    assert len(plan.beats) == 3
    assert plan.beats[0].start >= 0.24
    assert all(left.end <= right.start for left, right in zip(plan.beats, plan.beats[1:]))
    assert plan.beats[-1].end < plan.duration
    metadata = plan.metadata(
        "TMA-TEST",
        length_scale=1.0,
        words=[WordTiming(word="test", start=0.3, end=0.5, beat=1)],
        alignment_method="unit-test",
    )
    assert metadata.model_path.endswith(".onnx")
    assert metadata.duration == plan.duration


def test_tts_refuses_voice_without_declared_licence(repo_settings: Settings) -> None:
    raw = copy.deepcopy(repo_settings.raw)
    del raw["audio"]["voices"]["en_US-ljspeech-high"]["license"]
    settings = Settings(root=repo_settings.root, raw=raw, brand=repo_settings.brand)
    with pytest.raises(ConfigError, match="unknown or unsuitable licence"):
        voice_info(settings, "en_US-ljspeech-high")


def test_kokoro_produces_male_voice(repo_settings: Settings) -> None:
    pytest.importorskip("kokoro_onnx")
    if not repo_settings.path("assets/tts/kokoro/kokoro-v1.0.onnx").is_file():
        pytest.skip("Kokoro model is not installed on this machine")
    script = _short_script()
    plan = KokoroTTSProvider(repo_settings, "am_michael").synthesize(script)
    assert plan.provider == "kokoro"
    assert plan.voice.license.lower() == "apache-2.0"
    assert plan.sample_rate == 24000
    assert plan.duration > 2.0
    assert len(plan.beats) == 3
    assert all(left.end <= right.start for left, right in zip(plan.beats, plan.beats[1:]))


def test_mastering_preserves_length_and_peak(repo_settings: Settings) -> None:
    rate = 24000
    time = np.arange(rate, dtype=np.float32) / rate
    samples = (0.12 * np.sin(2 * np.pi * 180 * time)).astype(np.float32)
    mastered = master_narration(samples, rate, repo_settings)
    assert len(mastered) == len(samples)
    assert float(np.max(np.abs(mastered))) <= 10 ** (-1.5 / 20.0) + 1e-5


def test_subtitle_cues_are_ordered_and_match_words() -> None:
    words = [
        WordCue("Elias's", 0.22, 0.50, 1),
        WordCue("newspaper", 0.54, 0.92, 1),
        WordCue("was", 0.96, 1.08, 1),
        WordCue("dated", 1.12, 1.40, 1),
        WordCue("tomorrow.", 1.44, 1.90, 1),
        WordCue("He", 2.30, 2.42, 2),
        WordCue("lived", 2.46, 2.72, 2),
        WordCue("alone.", 2.76, 3.10, 2),
    ]
    cues = build_cues(words)
    assert cues
    assert validate_cues(cues, words) == []
    assert cues[0].start >= 0.0
    for left, right in zip(cues, cues[1:]):
        assert right.start >= left.end - 0.03
    assert max(cue.end - cue.start for cue in cues) <= 5.2
    assert " ".join(cue.text.replace("\n", " ") for cue in cues).split() == " ".join(
        word.word for word in words
    ).split()


def test_subtitle_srt_ass_roundtrip(tmp_path: Path) -> None:
    cues = [
        SubtitleCue(1, 0.2, 1.6, "The corridor was\nempty."),
        SubtitleCue(2, 1.7, 3.0, "A door opened."),
    ]
    srt = write_srt(cues, tmp_path / "subs.srt")
    parsed = parse_srt(srt)
    assert [cue.text.replace("\n", " ") for cue in parsed] == [
        "The corridor was empty.",
        "A door opened.",
    ]
    ass = write_ass(cues, tmp_path / "subs.ass", SubtitleStyle())
    text = ass.read_text(encoding="utf-8-sig")
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text
    assert "Dialogue:" in text


def test_beat_alignment_interpolates_missing_word() -> None:
    tokens = ["The", "corridor", "was", "empty."]
    recognised = [("The", 0.0, 0.1), ("corridor", 0.12, 0.45), ("empty.", 0.8, 1.0)]
    cues = align_beat_tokens(tokens, recognised, beat_start=2.0, beat_duration=1.1)
    assert [cue.word for cue in cues] == tokens
    assert all(cue.start >= 2.0 for cue in cues)
    assert all(left.end <= right.start + 1e-6 for left, right in zip(cues, cues[1:]))
    assert cues[-1].end <= 3.1 + 0.35


def test_mix_ducking_and_wav_format(tmp_path: Path, repo_settings: Settings) -> None:
    rate = 48000
    n = int(2.6 * rate)
    time = np.arange(n) / rate
    narration = np.zeros(n, dtype=np.float32)
    active = (time >= 0.6) & (time <= 1.6)
    narration[active] = (0.3 * np.sin(2 * np.pi * 180 * time[active])).astype(np.float32)
    narration_path = write_wav(tmp_path / "narration.wav", narration, rate)
    score = generate_score(tmp_path / "score.wav", 2.6, bpm=66, seed=3)
    mix = mix_audio(
        narration_path,
        score,
        [],
        tmp_path / "mix.wav",
        duration=2.6,
        settings=repo_settings,
    )
    samples, out_rate, channels = read_wav(tmp_path / "mix.wav")
    assert out_rate == 48000
    assert channels == 2
    assert samples.shape[0] == int(2.6 * rate)
    assert float(np.max(np.abs(samples))) <= 0.9
    assert mix.duration == 2.6
    envelope = _duck_envelope(narration, rate, -10.0)
    assert envelope[int(1.0 * rate)] < 0.6
    assert envelope[int(2.4 * rate)] > 0.9


def test_scene_timings_scale_to_audio_duration(repo_settings: Settings) -> None:
    storyboard = Storyboard.model_validate_json(
        (REPO_ROOT / "samples/demo_storyboard.json").read_text(encoding="utf-8")
    )
    timings = scale_scene_timings(storyboard, 54.131, repo_settings)
    assert timings[0].start == 0.0
    assert abs(timings[-1].end - 54.131) < 0.01
    assert abs(sum(item.duration for item in timings) - 54.131) < 0.02
    assert all(item.clip_duration > item.duration for item in timings[:-1])
    assert all(item.transition_out >= 0.0 for item in timings)


def test_asset_manager_rejects_unknown_licence(tmp_path: Path, project: Settings, db: Database) -> None:
    video = db.create_video(
        title="Asset Test",
        category="mystery",
        premise="A test premise for asset registration.",
    )
    video = db.transition(video["id"], "SELECTED")
    file_path = tmp_path / "still.png"
    file_path.write_bytes(b"not really a png")
    manager = AssetManager(project, db)
    with pytest.raises(ConfigError, match="unknown or unsuitable licence"):
        manager.register(
            video["id"],
            file_path,
            "image",
            source="test",
            license_name="unknown",
        )
    entry = manager.register(
        video["id"],
        file_path,
        "image",
        source="generated by test",
        license_name="Original",
        attribution="test",
    )
    assert entry.commercial_use is True
    assert manager.manifest_path.is_file()
    rows = db.list_assets(video["id"], "image")
    assert len(rows) == 1
    assert bool(rows[0]["commercial_use"]) is True


def test_short_render_and_technical_qc(tmp_path: Path, repo_settings: Settings) -> None:
    script = _short_script()
    storyboard = _short_storyboard()
    images: list[Path] = []
    for scene in storyboard.scenes:
        image = generate_still(scene, repo_settings, 700 + scene.scene)
        path = tmp_path / f"scene-{scene.scene:02d}.png"
        image.save(path)
        images.append(path)

    cues = [
        SubtitleCue(1, 0.2, 1.6, "The corridor was empty."),
        SubtitleCue(2, 1.7, 3.0, "A door opened."),
        SubtitleCue(3, 3.2, 4.2, "Nobody was there."),
    ]
    srt = write_srt(cues, tmp_path / "subs.srt")
    ass = write_ass(cues, tmp_path / "subs.ass", SubtitleStyle.from_settings(repo_settings))

    rate = 48000
    n = int(4.5 * rate)
    time = np.arange(n) / rate
    tone = (0.32 * np.sin(2 * np.pi * 190 * time)).astype(np.float32)
    tone[: int(0.1 * rate)] = 0
    tone[int(4.3 * rate) :] = 0
    mix = np.column_stack([tone, tone * 0.92]).astype(np.float32)
    mix_path = write_wav(tmp_path / "mix.wav", mix, rate)

    result = VideoRenderer(repo_settings).render(
        "TMA-TEST",
        storyboard,
        images,
        ass,
        mix_path,
        mix_path,
        tmp_path / "short.mp4",
        work_dir=tmp_path / "render-work",
    )
    assert result.mp4_path.is_file()
    probe = probe_media(result.mp4_path)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (1080, 1920)
    assert video["pix_fmt"] == "yuv420p"
    assert audio["codec_name"] == "aac"
    assert abs(float(probe["format"]["duration"]) - 4.5) < 0.15

    words = [
        WordTiming(word="The", start=0.2, end=0.3, beat=1),
        WordTiming(word="corridor", start=0.3, end=0.6, beat=1),
        WordTiming(word="was", start=0.6, end=0.8, beat=1),
        WordTiming(word="empty.", start=0.8, end=1.6, beat=1),
        WordTiming(word="A", start=1.7, end=1.8, beat=2),
        WordTiming(word="door", start=1.8, end=2.1, beat=2),
        WordTiming(word="opened.", start=2.1, end=3.0, beat=2),
        WordTiming(word="Nobody", start=3.2, end=3.5, beat=3),
        WordTiming(word="was", start=3.5, end=3.7, beat=3),
        WordTiming(word="there.", start=3.7, end=4.2, beat=3),
    ]
    narration = NarrationMetadata(
        video_id="TMA-TEST",
        provider="piper",
        voice="test",
        model_path="assets/voices/test.onnx",
        license="Public Domain",
        sample_rate=48000,
        duration=4.5,
        length_scale=1.0,
        alignment_method="unit-test",
        beats=[
            NarrationBeatTiming(beat=1, text="The corridor was empty.", start=0.2, end=1.6, duration=1.4),
            NarrationBeatTiming(beat=2, text="A door opened.", start=1.7, end=3.0, duration=1.3),
            NarrationBeatTiming(beat=3, text="Nobody was there.", start=3.2, end=4.2, duration=1.0),
        ],
        words=words,
    )
    report = run_technical_qc(
        "TMA-TEST",
        result.mp4_path,
        srt,
        narration,
        script,
        result.metadata,
        repo_settings,
        expected_scene_count=3,
    )
    failures = [f"{check.name}: {check.detail}" for check in report.checks if not check.passed]
    assert report.passed, failures
    assert report.probe["video_codec"] == "h264"
    assert report.probe["audio_codec"] == "aac"
