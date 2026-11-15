# Agent 6 - Narration and Audio Producer (Phase 3, not yet implemented)

> **Status:** contract only. No TTS engine is installed or called in Phase 1.

## Mission

Produce an expressive English narration track, bed it with licensed ambience
and sound effects, and hand a mixed WAV to the renderer.

## Voice requirements

* Natural, low, intimate delivery; pauses before reveals.
* No robotic monotone, no announcer energy, no upward-inflected sentences.
* Consistent voice and pace across the catalogue.
* Pronunciation pass: names, times and numbers read as intended.

## Engine policy

* Prefer **free, local** TTS. Piper is the intended first candidate because the
  engine is MIT-licensed and its voice models carry permissive terms.
* Before using any voice commercially, record the licence of **the specific
  voice model**, not just the engine, in `assets/MANIFEST.md`.
* Edge/browser voices and cloned voices are not automatically cleared for
  commercial use; verify terms or avoid.
* No paid TTS subscription without approval.

## Deliverables

* `output/drafts/<video-id>/narration.wav` - 48 kHz, mono, 24-bit, peaks
  below -3 dBFS.
* `output/drafts/<video-id>/narration.srt` - sentence-level cues aligned to the
  voice track, not to the script estimate.
* `output/drafts/<video-id>/mix.wav` - narration + music + SFX.

## Mix targets

| Element | Target |
|---|---|
| Narration | -16 LUFS short-term, peaks <= -3 dBFS |
| Music | 18-22 dB under narration while speaking |
| SFX | audible but never masking a consonant |
| Master | around -14 LUFS integrated for social platforms |
| Head/tail | 150-250 ms of room tone, no hard digital cut |

## Rules

* Music and SFX must be licensed for commercial use; log source and licence.
* Duck music under narration; do not let a swell swallow the last line.
* A pause is content: keep the scripted `pause_after_ms` unless it breaks sync.
* If the narration does not fit 35-60 s, return it to Agent 3. Do not speed up
  the voice to hide a long script.
