# TMA-0001 v3 full narration review — `bm_george`

**Review only. Project status before and after: `STORYBOARD_READY`. No asset stage, render, QC approval or publication was performed.**

## Selection verified

- Handoff: `C:/Users/LOQ/Documents/Codex/2026-11-15/c-users-loq-config-freebuff-desktop/outputs/tma-0001-v3-audition-review-v1/voice-selection-v1.json`
- Handoff SHA-256: `4c7e1854758e33421c461d016a28b407575eb0654350ea41a486b903a3836952`
- Audition WAV hash in the handoff matches `output/voice_tests/v2/level-matched/kokoro-bm_george-reference.wav`.
- Selected: Kokoro-82M `bm_george`, `en-gb`, speed **0.96**, Apache-2.0 model/voices, MIT runtime.
- Previous working config archived at `config/archive/settings-v2-am_michael.yaml`.
- Selection record: `output/voice_selection/TMA-0001-narrator-v3.json`.

**Handoff discrepancy:** the approved audition WAV was generated with the `en-us` G2P tag on the British voice. The handoff requests `en-gb`; that is what this full read uses. `en-gb` changes vowel rendering and timing, so this is a new review item, not a byte-identical replay of the 18.293 s audition.

## Full read

| Item | Result |
|---|---|
| Audio | `narration.wav` — **59.838 s**, 24 kHz mono |
| Peak | −1.5 dBFS; true peak −1.5 dBTP |
| Integrated loudness | −18.7 LUFS |
| Clipping samples | 0 |
| Silence over 0.6 s | 5; longest 1.074 s |
| Script coverage | 129/129 words, 13 beats |
| Alignment | faster-whisper word timestamps per beat; 0 warnings |
| Subtitles | 26 cues, 58.756 s span; SRT + ASS |
| Subtitle text vs script | exact after normalisation |
| Status unchanged | yes |

The review removes **0.500 s of unused trailing near-silence** from the 800 ms production tail. No speech, beat or pause was removed. The raw pre-trim read was 60.358 s; this trimmed review is 59.838 s.

## Pronunciation

Target G2P for `en-gb`:

| Name | Phonemes | Intended reading |
|---|---|---|
| Elias | `ɪlˈaɪəs` | ih-LYE-us |
| Voss | `vˈɒs` | Voss (British short o; final s) |
| Mara | `mˈɑːɹə` | MAH-rə |
| Kwan | `kwˈan` | Kwan |

The **full-context ASR heard “Elias,” “Mara” and “Kwan” correctly**, with no suspicious variants. It also heard 4A/4B and 3:07 correctly. `Voss` does not occur in the spoken script; it is only in on-screen obituary text, so the isolated `elias-voss.wav` probe is the only check for that surname.

The isolated probes are deliberately short and are **not reliable ASR evidence**: “Elias Voss” was transcribed as “Elias Vos” (weak final s), and “Mara Kwan” as “Mora-Quand.” The full sentence context is the stronger signal. A human must still listen to the full read and the probes before this is treated as pronunciation approval.

Probe files: `pronunciation-probes/elias-voss.wav`, `mara-kwan.wav`, `pair.wav`.

## Version note

- `v1` — first full read, 60.358 s, over the 60 s ceiling.
- `v2` — experimental “Mara Kwahn” override; rejected because the full-read ASR became “Marquan.”
- `v3` — clean read with the authored “Mara Kwan,” trailing-silence trim, passing checks.

Failed/intermediate versions are retained. No committed script, storyboard, MP4 or prior config was overwritten.

## Decision

Listen to `narration.wav`, then check `pronunciation-probes/elias-voss.wav` and `mara-kwan.wav`. Do not render the video until explicitly authorized.
