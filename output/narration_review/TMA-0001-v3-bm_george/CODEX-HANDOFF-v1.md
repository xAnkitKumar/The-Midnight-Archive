# TMA-0001 v3 — Freebuff handoff to Codex

**Date:** 2026-11-15 (local) / 2026-11-15T00:00Z context
**Status:** `STORYBOARD_READY` — full narration review ready, **not approved, not rendered**
**Selected narrator:** Kokoro-82M `bm_george`, `en-gb`, speed 0.96

## Inputs verified

- Handoff JSON: `C:/Users/LOQ/Documents/Codex/2026-11-15/c-users-loq-config-freebuff-desktop/outputs/tma-0001-v3-audition-review-v1/voice-selection-v1.json`
- Handoff SHA-256: `4c7e1854758e33421c461d016a28b407575eb0654350ea41a486b903a3836952`
- Audition hash matches `output/voice_tests/v2/level-matched/kokoro-bm_george-reference.wav`.
- Script v3 and storyboard v3 in the DB match their JSON files.
- Note: the audition hash was generated with the `en-us` G2P tag; the handoff and full read use `en-gb`. This is documented, not silently changed.

## What Freebuff changed

- Active `config/settings.yaml`: `voice: bm_george`, `language: en-gb`, `bm_george.speed: 0.96`.
- Previous config archived at `config/archive/settings-v2-am_michael.yaml`.
- Selection record: `output/voice_selection/TMA-0001-narrator-v3.json`.
- Fixed `Pipeline.narrate` so a successful narration job replays before the
  `ASSETS_READY` status gate; added a regression test. Nothing in the shared
  pipeline was advanced or rendered.
- Added `experiments/narration_review.py`, an isolated review runner that cannot
  prepare assets, mix, register artifacts, transition status, render or approve.

## Full narration review

- `output/narration_review/TMA-0001-v3-bm_george/v3/narration.wav`
- 59.838 s, 24 kHz mono, −1.5 dBFS peak, −18.7 LUFS, true peak −1.5 dBTP, no clipping.
- 129/129 words, 13 beats; 26 subtitle cues; 0 alignment warnings; subtitle text matches script.
- `subtitles.srt`, `subtitles.ass`, `narration-metadata-v1.json`, `alignment-v1.json`.
- `audio-qc-v1.json`: `passed: true`.
- Trailing 0.500 s of unused near-silence was trimmed from the 800 ms production tail; speech and pauses are unchanged.
- Version history: v1 (60.358 s, over), v2 (rejected “Mara Kwahn” override), v3 (clean review).

## Pronunciation

- Full-context ASR heard Elias, Mara and Kwan correctly.
- Target G2P: Elias `ɪlˈaɪəs`; Voss `vˈɒs`; Mara `mˈɑːɹə`; Kwan `kwˈan`.
- Isolated probes are unreliable ASR; they are listening prompts, not a verdict.
- Human listening is still required for the names and the full read.

## Coordination boundary

Do **not** run `assets`, `narrate`, `render`, `qc`, `approve` or `publish` for
TMA-0001 until the owner reviews the v3 narration. If another production step is
authorized, use the active `bm_george` config and preserve all v1/v2/v3 folders,
existing MP4s and DB history. The current review is intentionally outside the
production status machine.
