# The Midnight Archive

A local-first production studio for faceless short-form storytelling: original
psychological horror, mystery and mind-bending stories for Instagram Reels.

Phase 1 is the **story development pipeline**: a strict database, validated JSON
handoffs between agent roles, editorial gates, a CLI and tests. Phase 2 adds a
complete local production slice: Kokoro narration (Piper fallback), faster-whisper subtitle
alignment, an asset/licence registry, a procedural visual and audio bed, an
FFmpeg vertical renderer, and technical QC of the actual MP4.

AI image generation and Instagram automation are still deliberately **not built**.

---

## Current status

| Phase | Scope | Status |
|---|---|---|
| 1 | Environment, config, SQLite, ideas, script + storyboard validation, CLI, tests | **Done** |
| 2 | Local TTS, aligned subtitles, asset licensing, original placeholder visuals, score/SFX, FFmpeg render, technical MP4 QC | **Done for TMA-0001** |
| 3 | AI image generation and character consistency | Not started |
| 4 | Instagram automation, YouTube Shorts adapter | Not started |
| 5 | Richer analytics | Not started |

What the app can do today:

* generate 15 scored, de-duplicated story ideas per session with zero API cost;
* register a selected concept and track it through the full status machine;
* validate a hand-written or agent-written script against word count, duration,
  banned phrasing, continuity flags and source compliance;
* validate a storyboard: scene timing, narration coverage, prompts, SFX;
* run an automatic script preflight score;
* record a 100-point QC report and enforce the 80/100 gate;
* record human approval and manual publishing, with immutable final states;
* record manually entered Instagram performance numbers;
* synthesize narration locally with Kokoro (default) or Piper (fallback), preserving scripted pauses and recording
  voice/model/licence provenance;
* align word timestamps per narration beat with faster-whisper and export SRT + ASS;
* register every font, voice, image, music cue and SFX with a commercial licence,
  attribution and SHA-256 in `assets/manifest.json`;
* generate deterministic Pillow scene stills, an original procedural score and SFX;
* mix narration, ducked music and SFX, render 1080x1920 H.264/AAC with zoom/pan,
  xfade transitions and burned-in subtitles;
* inspect the MP4 with FFprobe/FFmpeg for codec, resolution, frame rate, duration,
  audio, black frames, silence, loudness, subtitle timing and full-decode integrity;
* export JSON Schemas for every handoff.

---

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

FFmpeg 9 with `libx264`, `aac`, `xfade`, `zoompan` and `ass` is required. On this
machine it is already installed via winget; `doctor` finds it on `PATH` or in the
per-user WinGet folder.

Two model files are downloaded separately and are **not** pip packages:

1. Kokoro-82M model and voice pack, placed in `assets/tts/kokoro/`:
   `kokoro-v1.0.onnx` and `voices-v1.0.bin`. Source:
   <https://huggingface.co/hexgrad/Kokoro-82M>. The model and voices are
   Apache-2.0; the `kokoro-onnx` runtime is MIT. `bm_george` is the human-selected
   narrator for TMA-0001 v3.
   Piper remains an optional fallback: `en_US-ljspeech-high.onnx` and its
   `.onnx.json` config go in `assets/voices/`. The LJSpeech dataset is public
   domain; the Piper **engine** is GPL-3.0, a separate licence.
2. `Montserrat-Bold.ttf` in `assets/fonts/`, licensed under SIL OFL 1.1, plus
   `Montserrat-OFL.txt`.

faster-whisper downloads its `base.en` model on first use into the user cache.
No paid API or account is required.

## Quick start (PowerShell, Windows)

The environment is already installed in this folder: Python 3.12.14 in `.venv`
and FFmpeg 9.0.2 via winget. Open a **new** PowerShell window so FFmpeg is on
`PATH`, then:

```powershell
cd "C:\Users\LOQ\.config\freebuff-desktop\local-projects\d923bc2c-a2d3-483f-bf76-c47cb7952c0b"

# 1. Check everything
.\.venv\Scripts\python.exe -m midnight_archive doctor

# 2. Generate 15 ideas (free, offline, deterministic with --seed)
.\.venv\Scripts\python.exe -m midnight_archive ideas --count 15 --label "week 1" --seed 20261114

# 3. Inspect the best ideas
.\.venv\Scripts\python.exe -m midnight_archive ideas --list

# 4. Turn one into a video at SELECTED
.\.venv\Scripts\python.exe -m midnight_archive select --idea IDEA-0008

# 5. Show its state and audit trail
.\.venv\Scripts\python.exe -m midnight_archive show --video TMA-0002

# 6. Run the tests
.\.venv\Scripts\python.exe -m pytest
```

On a fresh machine, `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1`
creates `.venv`, installs dependencies, checks FFmpeg and initialises the project.

### Demonstration already produced (v1/v2 render)

`TMA-0001` - *The Man Who Received Tomorrow's Newspaper* - has a v1/v2 MP4 and QC
from the earlier script. The current v3 creative revision is at `STORYBOARD_READY`,
awaiting a human narration audition (not approved, not published):

* 15 ideas generated in session `IDEAS-20261114T174959Z-4429`, scores 78-95,
  no repeated premise, title or hook.
* Script: **128 words**, **54.4 s** at 2.5 words/second including pauses.
* Automatic preflight: **90/100** (hook 30/30, pacing 25/25, suspense 10/20,
  ending 15/15, compliance 10/10).
* Storyboard: **8 scenes**, exactly **54.4 s**, narration covers every word.
* Narration: **54.79 s**, 128/128 aligned words, 31 subtitle cues, zero Whisper
  warnings. Voice: `en_US-ljspeech-high` (public-domain LJSpeech).
* Video: **54.80 s**, 1080x1920, 30 fps, H.264 High, AAC 48 kHz stereo, 49.70 MB.
* Technical QC: **31/31 checks passed**. Creative QC: **85/100**, verdict PASS.
* Output: `output/rendered/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v2.mp4`

Exact TMA-0001 production commands (already run; reruns are idempotent until a
render is reworked):

```powershell
.\.venv\Scripts\python.exe -m midnight_archive assets --video TMA-0001
.\.venv\Scripts\python.exe -m midnight_archive narrate --video TMA-0001
.\.venv\Scripts\python.exe -m midnight_archive render --video TMA-0001
.\.venv\Scripts\python.exe -m midnight_archive qc-check --video TMA-0001
.\.venv\Scripts\python.exe -m midnight_archive qc --video TMA-0001 --file output\qc\TMA-0001-creative-v1.json
```

Or from `STORYBOARD_READY`, run the deterministic stages in one command:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive produce --video TMA-0001
```

`produce` stops at `RENDERED`; it never records creative QC, approves or publishes.

Full narration:

> Elias's newspaper was dated tomorrow. He lived alone. He had no subscription.
> A misprint — until page nine reported his death. Apartment fire. Friday. Three
> a.m. His name. He booked a hotel across town. Saturday's paper was at the
> front desk. The fire happened anyway. Same building. Same hour. Different man.
> The dead man was his neighbour, who'd knocked to warn him. Elias spread every
> paper he'd saved across the floor. All dated tomorrow. Each mentioned him less
> than the last. First his job. Then his friends. Then the crossword. By Friday,
> his photograph was a grey rectangle. Saturday's paper arrived blank. Only the
> masthead remained. The Midnight Archive: all the news that never was. Elias
> finally understood. It wasn't predicting his future. It was deciding what to
> keep.

---

## Command reference

Run everything through the venv Python. Global options `--root` and `--verbose`
go **before** the command.

| Command | Purpose |
|---|---|
| `python -m midnight_archive doctor` | Check Python, FFmpeg/ffprobe, encoders, folders, DB |
| `python -m midnight_archive init` | Create folders, DB schema and `schemas/` |
| `python -m midnight_archive ideas --count 15 [--seed N] [--label TEXT]` | Generate and score ideas |
| `python -m midnight_archive ideas --list [--limit N] [--json]` | List stored ideas |
| `python -m midnight_archive select --idea IDEA-0008 [--title TEXT] [--force]` | Create a video from an idea (SELECTED) |
| `python -m midnight_archive select --video TMA-0001` | Move a manual IDEA video to SELECTED |
| `python -m midnight_archive new --title TEXT --category CATEGORY [--premise TEXT] [--select]` | Register a hand-picked concept |
| `python -m midnight_archive import-script --video TMA-0001 --file path.json` | Validate + attach script (SCRIPTED) |
| `python -m midnight_archive import-storyboard --video TMA-0001 --file path.json` | Validate + attach storyboard (STORYBOARD_READY) |
| `python -m midnight_archive review --video TMA-0001 [--json]` | Automatic script preflight score |
| `python -m midnight_archive assets --video TMA-0001` | Generate/register stills, score, SFX, font and voice (ASSETS_READY) |
| `python -m midnight_archive narrate --video TMA-0001` | Kokoro/Piper WAV, Whisper-aligned SRT/ASS, narration/music/SFX mix (AUDIO_READY) |
| `python -m midnight_archive render --video TMA-0001` | Render the versioned MP4 (RENDERED) |
| `python -m midnight_archive produce --video TMA-0001` | Run assets -> narration -> render, stopping at RENDERED |
| `python -m midnight_archive qc-check --video TMA-0001 [--json]` | FFprobe/FFmpeg inspection of the actual MP4 |
| `python -m midnight_archive qc --video TMA-0001 --file qc.json` | Record **creative** QC and apply the 80/100 gate; requires passing technical QC |
| `python -m midnight_archive approve --video TMA-0001 --reviewer NAME` | Human approval (requires QC pass + MP4) |
| `python -m midnight_archive publish --video TMA-0001 --url URL [--caption TEXT] [--hashtags "#a,#b"]` | Record a manual publication |
| `python -m midnight_archive show --video TMA-0001 [--json]` | Full record and audit trail |
| `python -m midnight_archive list [--status STATUS]` | List videos |
| `python -m midnight_archive stats add --video TMA-0001 --views 1200 --likes 90 ...` | Manual performance snapshot |
| `python -m midnight_archive stats show [--video TMA-0001]` | Performance table |
| `python -m midnight_archive export-schemas` | Regenerate `schemas/*.schema.json` |

Exit codes: `0` success, `1` runtime refusal (wrong status, missing file),
`2` validation rejected (script/storyboard/QC).

### Typical production loop

```text
ideas -> select -> import-script -> import-storyboard -> assets -> narrate
      -> render -> qc-check -> qc -> approve -> manual Instagram upload -> publish
```

`qc-check` is the technical gate; `qc` is the human/agent creative report. Both
must pass before approval. `approve` copies the versioned artifacts, MP4, audio,
subtitles and stills into `output/approved/<video-id>/`. Publishing remains a
manual action followed by `publish --url ...` to record it.

---

## Phase 2 implementation notes

### What is local and licensed

| Component | Use | Licence / provenance |
|---|---|---|
| Kokoro-82M `bm_george` | narration voice (default) | Apache-2.0 model/voices |
| `kokoro-onnx 0.6.1` | Kokoro ONNX runtime | MIT |
| Piper `piper-tts 1.8.0` | local speech synthesis (fallback) | GPL-3.0 engine |
| `en_US-ljspeech-high` | Piper fallback voice | public-domain LJSpeech; MODEL_CARD records the dataset |
| faster-whisper `1.2.1` + `base.en` | per-beat word timestamps | MIT; model downloaded on first use |
| Montserrat Bold | burned-in subtitles | SIL OFL 1.1 |
| Pillow stills | placeholder scene art | original, generated locally |
| NumPy score/SFX | music and effects | original, synthesized locally; no samples |

The licence of a voice is checked separately from the engine. `assets/manifest.json`
records asset ID, path, type, source, licence, commercial permission, attribution
and SHA-256. Unknown or non-commercial licences are rejected unless
`assets.allow_unlicensed` is explicitly enabled for test-only material.

### Media and QC design

* Narration is synthesized **per script beat**. The AV WAV keeps a 250 ms lead-in,
  each beat's scripted pause and an 800 ms Kokoro tail (700 ms for Piper). Provider, voice, model path,
  licence, duration, speed setting, beat timings and 128 word timings are stored
  in `output/narration_metadata/`.
* Subtitle timestamps are **not** estimated by dividing the video duration. Each
  beat's synthesized audio is transcribed with faster-whisper word timestamps,
  matched to the authored tokens and offset by the measured beat start. A failed
  individual beat is interpolated only inside that beat, and the method records it.
* ASS is generated at `PlayResX=1080`, `PlayResY=1920` and burned with Montserrat,
  a 4 px outline, bottom-centre alignment, `MarginV=260`. SRT is exported too.
* Scene durations scale from the storyboard to the measured audio length. Each
  still gets a slow zoom and 12-frame-safe 30 fps clip; transitions use xfade.
  The renderer takes a storyboard, image list and audio/subtitle paths, so it is
  not hardcoded to TMA-0001.
* The score is a procedural D-minor drone with sparse piano-like notes; SFX are
  shaped noise/impulses. Music sits at -24 dB and ducks by -10 dB under narration.
* Technical QC uses FFprobe plus FFmpeg `blackdetect`, `silencedetect`,
  `volumedetect`, `ebur128` and a full decode. It is stored separately in the
  `technical_checks` table. A passing MP4 does not earn creative points; the
  creative report is still authored independently against the 80/100 rubric.

### TMA-0001 verified output

Path:

```text
output/rendered/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v2.mp4
```

FFprobe (v2):

```text
format_name=mov,mp4,m4a,3gp,3g2,mj2
format duration=54.800000 s
format size=49.70 MB
video codec=h264 (High), 1080x1920, yuv420p, 30/1 fps
video SAR=1:1, DAR=9:16
audio codec=aac, 48000 Hz, 2 channels
audio duration=54.793 s
peak_volume=-1.0 dBFS, mean_volume=-16.2 dBFS
integrated_loudness=-12.9 LUFS
black frames: none outside the intended fades
silent sections: none unexpected
full decode: clean
```

Technical checks: **31/31 PASS**. Creative report: **85/100 PASS**
(hook 14/15, originality 8/10, coherence 14/15, suspense 13/15, ending 15/15,
voice 7/10, visual consistency 5/10, subtitle sync 5/5, audio mix 4/5).

### Remaining limitations

* The eight images are deliberately stylised Pillow placeholders, not finished
  character art. They establish palette and composition but do not show faces or
  detailed hands; AI image generation was explicitly out of scope.
* Kokoro `bm_george` is the human-selected narrator. The full-length review is in
  `output/narration_review/TMA-0001-v3-bm_george/v3/`; it has not been reviewed by
  a human, and no full Kokoro render exists.
* The score and SFX are synthetic and intentionally sparse. No human listening
  pass or external mastering was performed; integrated loudness is -12.9 LUFS
  rather than the configured -14 target.
* Subtitle text and timing pass machine checks and frame inspection; a final
  human proofread is still recommended before publishing.
* Piper's GPL-3.0 engine has distribution obligations if the application itself
  is redistributed. The voice model's public-domain status is separate.
* Instagram upload and AI image generation are not implemented. Approval and
  publication are never automatic.

---

## Demonstration commands

The demo inputs are in `samples/` and can be replayed in a fresh project:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive new `
  --title "The Man Who Received Tomorrow's Newspaper" `
  --category mind_bending `
  --premise "A man receives a newspaper dated tomorrow that begins erasing him from the record." `
  --select

.\.venv\Scripts\python.exe -m midnight_archive import-script `
  --video TMA-0001 --file samples\demo_script.json

.\.venv\Scripts\python.exe -m midnight_archive import-storyboard `
  --video TMA-0001 --file samples\demo_storyboard.json

.\.venv\Scripts\python.exe -m midnight_archive review --video TMA-0001
.\.venv\Scripts\python.exe -m midnight_archive show --video TMA-0001
```

`import-script` is idempotent: re-importing the identical JSON returns a replay
and writes no second artifact. Changed JSON creates `v2`; nothing is overwritten.

---

## Architecture

```text
                      config/settings.yaml + config/brand.yaml
                                     |
  CLI (argparse + rich) ---------> Settings
      |                                |
      |  ideas / select                |
      v                                v
  providers.py  ----------------> story_generator.py
  (offline | opt-in LLM)              |
                                      v
                               models.py (Pydantic, strict)
                                      |
                       +--------------+--------------+
                       |                             |
                 database.py                    pipeline.py
             (SQLite, statuses,             (imports, QC,
              jobs, dupes, audit)             approval, publish)
                       |                             |
                       +-------- output/<kind>/<video>-<slug>-vN.json
                                      |
                              logs/midnight.log
```

### Why this shape

**Agent roles are contracts, not microservices.** Eight independent LLM services
would be expensive, flaky and impossible to audit. Each role is a Markdown
contract in `agents/`, and its output is a Pydantic-validated JSON file. Freebuff
chat agents (or a future LLM adapter) do the creative work; the Python app owns
state, validation, versioning and refusal. This is cheaper, reproducible and
debuggable.

**Strict JSON instead of "the model said so".** `extra="forbid"`, computed
fields and explicit maxima mean a malformed handoff fails at the boundary, not
in the renderer. The JSON Schemas in `schemas/` are exported from the same
Python classes, so contracts cannot drift.

**SQLite instead of folders-as-state.** Status history, duplicate detection,
artifact hashes and job retries need transactions. A status is not a folder
rename: `APPROVED` is enforced as terminal in both the DB and the pipeline.

**Versioned artifacts instead of overwrites.** Every import writes
`v1`, `v2`, ... and records a SHA-256. Approval copies the final bundle into
`output/approved/<id>/` and refuses to overwrite it.

**Offline ideation is a starting point, not a writer.** The combinatorial engine
is free, deterministic and good at volume and variety. Its premises still need
a human/agent to write the actual story. A paid adapter exists but is gated and
has not been exercised against a live endpoint.

**Package layout.** The code lives in `midnight_archive/` rather than `src/` so
`python -m midnight_archive` works with no editable install on Windows. The
requested structure is otherwise preserved; empty stub modules were not created.

### Status machine

```
IDEA -> SELECTED -> SCRIPTED -> STORYBOARD_READY -> ASSETS_READY -> AUDIO_READY
     -> RENDERED -> QUALITY_CHECKED -> AWAITING_APPROVAL -> APPROVED -> PUBLISHED
```

One-step rework edges exist (`SCRIPTED -> SELECTED`, `STORYBOARD_READY ->
SCRIPTED`, etc.). `APPROVED` and `PUBLISHED` have no outgoing edges.

### Data model

* `videos` - id, title (unique key), category, status, premise, source, script
  and storyboard JSON, hashes, QC totals, timestamps.
* `idea_sessions`, `ideas` - batches and scored candidates, unique premise hash.
* `status_events` - every transition with actor, reason and time.
* `artifacts` - versioned files with SHA-256.
* `quality_reports` - full QC JSON and verdict.
* `publications`, `performance_stats` - manual publishing and metrics.
* `jobs` - idempotency key, attempts, error, timestamps.

---

## Project layout

```
the-midnight-archive/
  AGENTS.md                 operating rules for coding/content agents
  README.md
  requirements.txt
  .env.example              env template, no secrets
  config/                   settings.yaml + brand.yaml
  agents/                   7 role contracts
  schemas/                  exported JSON Schemas (committed)
  midnight_archive/         Python package
    cli.py config.py models.py database.py pipeline.py providers.py
    story_generator.py script_editor.py storyboard.py quality_check.py
    analytics.py doctor.py schemas.py logging_utils.py utils.py errors.py
  samples/                  demo script + storyboard
  scripts/                  setup.ps1, generate_ideas.py, produce_story.py
  tests/                    80 tests
  data/                     archive.db, ideas/, analytics/
  assets/                   characters, backgrounds, music, sfx, fonts
                            + MANIFEST.md licence register
  output/                   scripts, storyboards, drafts, rendered,
                            approved, published
  logs/
```

---

## Editorial and technical gates

| Gate | Rule | Where |
|---|---|---|
| Word count | 90-130 spoken words | `config/settings.yaml`, `script_editor.py` |
| Duration | 35-60 s at 2.5 words/s + pauses | same |
| Hook | warning above 12 words | same |
| Banned phrasing | hard error | `config/settings.yaml` |
| Adaptation | source reference + public-domain flag required | `models.py` |
| Storyboard coverage | every script word in exactly one scene | `storyboard.py` |
| Storyboard timing | contiguous, 35-60 s, 1.2-12 s per scene | `storyboard.py` |
| QC | >= 80/100 and no blocking issues | `quality_check.py` |
| Approval | QC pass + rendered MP4 + human name | `pipeline.py` |
| Publication | approved only, URL recorded, bundle archived | `pipeline.py` |

---

## Cost, security and licensing

* Monthly spend so far: **₹0**. Python, FFmpeg, SQLite and the idea engine are
  free and local.
* The offline provider makes **no network calls**. The paid adapter requires
  `TMA_ALLOW_PAID_API=1` **and** `--allow-paid-api`; neither is set.
* Secrets belong in `.env` (git-ignored). Logging redacts `sk-...`, bearer
  tokens and values of `*_API_KEY`/`*_TOKEN`/`*_SECRET` variables.
* No modern copyrighted text. Adaptations must be public domain with a recorded
  source. Every third-party asset needs a row in `assets/MANIFEST.md`.
* Publication is manual. The app never logs into Instagram.

---

## Manual publishing checklist (Phase 1)

1. Watch the final MP4 on a phone, sound on, then muted.
2. Confirm subtitles are readable at thumb distance and in sync.
3. Confirm no factual claim is presented as science and no asset is unlicensed.
4. Upload the 1080x1920 / 30 fps / H.264 + AAC MP4 as a Reel; choose a cover
   frame that reads at grid size.
5. Paste the caption + 5-8 hashtags from `config/brand.yaml`.
6. Copy the Reel URL and record it:
   `python -m midnight_archive publish --video TMA-0001 --url <url>`.
7. After 24 h and 7 days, record views/likes/comments/shares/saves with
   `stats add`.

Generated captions, hashtag sets and cover images are Phase 4 deliverables.
Until then, write them by hand from the brand file.

---

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

80 tests, all passing. They cover config loading, the status machine and
terminal states, duplicate titles/premises/scripts, artifact versioning, job
retries and idempotency, script gates, storyboard timing and coverage, QC
thresholds, approval/publish refusals, CLI exit codes, the demo artifacts and
schema export. Tests use isolated temporary projects; they never touch the real
database or the network.

---

## Known limitations

* **No video exists yet.** `qc`, `approve` and `publish` cannot be reached by the
  CLI until Phase 4 produces an MP4. The gate logic is implemented and tested
  with a dummy file.
* **No font installed.** `assets/fonts/` is empty; Phase 4 subtitles need an
  OFL font.
* **Offline ideas are formulaic.** They are structured starting points; the
  story architect rewrites them. The LLM adapter is untested without a key.
* **The paid adapter is experimental.** It speaks the OpenAI chat-completions
  shape and has explicit cost gates, but has never made a live call here.
* **Windows-first.** Paths and setup scripts target Windows; the Python code
  itself is portable.
* **Script revisions are versioned.** A revised script can be imported while the
  video is `SELECTED` or reopened as `SCRIPTED`; it creates `v2` and leaves the
  previous artifact in history. Other stages still require an explicit rework
  transition before a new script can be attached.

---

## Next phase (recommended)

**Phase 2 - prove the pipeline end-to-end before making it pretty.**

1. Add an offline renderer: stills + Ken Burns + burned-in subtitles + SRT +
   music bed, using FFmpeg. Use storyboard scene timings directly.
2. Add local TTS (Piper) behind a provider interface, with licence recording.
3. Add `asset_manager.py`: provider adapters, character reference sheets,
   asset hashing and `assets/MANIFEST.md` updates. No paid calls.
4. Add `render --video` and extend `qc` to inspect the real MP4 (duration,
   resolution, fps, audio peaks, subtitle coverage).
5. Only then invest in image generation quality.

This order proves the riskiest part (a complete, watchable MP4) with minimal
spend, and keeps every later improvement inside a validated stage.
