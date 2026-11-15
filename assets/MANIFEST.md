# Asset Manifest

The authoritative, machine-maintained registry is **`assets/manifest.json`**.
It records asset ID, file path, type, provider, source, licence, commercial-use
permission, attribution, SHA-256 and the video that used the asset. It is written
by `midnight_archive/asset_manager.py`; do not hand-edit the JSON.

This Markdown file remains the human-readable policy/register and is updated when
the licence position changes.

## Current registered media (TMA-0001)

| File | Type | Source / Provider | Licence | Attribution | Used in |
|---|---|---|---|---|---|
| `assets/tts/kokoro/kokoro-v1.0.onnx` + `voices-v1.0.bin` | voice model + pack | Kokoro-82M / hexgrad; `kokoro-onnx` runtime | Apache-2.0 (model/voices); MIT (runtime) | Kokoro-82M by hexgrad; voice `am_michael` | TMA-0001 audition |
| `assets/voices/en_US-ljspeech-high.onnx` + `.onnx.json` | voice model | Piper / `rhasspy/piper-voices` | Public Domain (LJSpeech) | LJSpeech dataset; Piper voice trained by Bryce Beattie | TMA-0001 fallback |
| `assets/fonts/Montserrat-Bold.ttf` + `Montserrat-OFL.txt` | font | Julieta Ulanovsky / Montserrat | SIL OFL 1.1 | Montserrat by Julieta Ulanovsky | TMA-0001 |
| `assets/music/midnight-score.wav` | music | Generated locally with NumPy; no samples | Original | The Midnight Archive procedural score | TMA-0001 |
| `assets/sound_effects/*.wav` (12 files) | SFX | Generated locally with NumPy; no samples | Original | The Midnight Archive procedural SFX | TMA-0001 |
| `output/drafts/TMA-0001/images/scene-01.png` ... `scene-08.png` | images | Generated locally with Pillow from the storyboard | Original | The Midnight Archive procedural still | TMA-0001 |
| `output/drafts/TMA-0001/audio/narration-v1.wav` | narration | Piper `en_US-ljspeech-high` | Public Domain voice | Voice provenance recorded in narration metadata | TMA-0001 |
| `output/drafts/TMA-0001/audio/mix-v1.wav` | audio mix | Local mix of narration, score and SFX | Original | The Midnight Archive local mix | TMA-0001 |

## Rules

* One row per asset, exact filename, exact licence name and source URL.
* Generated images: record provider, model, seed and prompt file. A generated
  image still has terms of use. The current stills are original Pillow drawings.
* Music and SFX: only commercial-use licences. Current files are synthesized
  from sine/noise primitives, not samples, and are recorded as Original.
* Fonts: record the font licence; OFL fonts are preferred.
* Never delete a row for an asset used in an approved or published video.
* Unknown or non-commercial licences are rejected by `AssetManager.register`
  unless `assets.allow_unlicensed` is explicitly enabled for test-only material.
