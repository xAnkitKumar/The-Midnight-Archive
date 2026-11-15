# AGENTS.md - working rules for The Midnight Archive

This repository is a **production studio**, not a demo. Every stage produces a
validated artifact that the next stage consumes. Read this file before changing
code or generating content.

## Non-negotiable rules

1. **No automatic publishing.** A human approves every video. The CLI can only
   record a publication that the owner performed manually.
2. **No spending.** No paid API, subscription or asset purchase without the
   owner's explicit approval. The paid LLM adapter is disabled by default and
   requires both `TMA_ALLOW_PAID_API=1` and `--allow-paid-api`.
3. **No secrets in the repo.** Keys live in `.env` (git-ignored) or the
   environment. Never print, log or commit them. `logging_utils.redact()` is a
   safety net, not permission.
4. **Original content only.** Write original stories, or adapt verified
   public-domain works with `source.reference` filled in. Never reproduce
   modern copyrighted text, translations or adaptations.
5. **Never modify an APPROVED or PUBLISHED video.** The database enforces
   terminal states and the pipeline refuses writes. Create a new video instead.
6. **Never overwrite artifacts.** Use versioned filenames (`-v1`, `-v2`, ...).
7. **Never claim untested behaviour.** If a stage has not run, say so.

## What exists today (Phase 2)

Implemented: config, SQLite job management, idea generation and scoring,
script validation and preflight, storyboard validation, the full status flow,
creative QC, approval and publishing records, manual analytics, JSON schema
export, CLI, tests.

Phase 2 adds: replaceable local TTS (Kokoro default, Piper fallback); per-beat faster-whisper word
alignment to SRT/ASS; an asset registry with commercial-licence checks; original
Pillow stills; a procedural score and SFX; an FFmpeg 1080x1920 renderer with
zoom, xfade and burned-in subtitles; and technical MP4 QC (`qc-check`) stored
separately from creative QC.

Not integrated in the Python app: AI image generation, automated character consistency,
Instagram automation or YouTube Shorts publishing. The archived test preview used a
chat image tool and explicit reference images. Do not invent models, licences or media.

The archived TMA-0001 script v3 and approved bm_george narration v4 produced a
55.20-second full test preview (MP4 v3), with timing-only storyboard v4 and 31/31
technical QC checks passing. The video remains RENDERED for human review; no
release approval or publication has occurred. Narration approval is separate.

## Environment

* Windows 10/11, PowerShell 7, Python 3.12 in `.venv`, FFmpeg 9 (winget).
* Run every command from the repository root, with the venv Python:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive --help
.\.venv\Scripts\python.exe -m pytest
```

Never use the Microsoft Store `python.exe` alias; it is a stub on this machine.

## Status machine

```
IDEA -> SELECTED -> SCRIPTED -> STORYBOARD_READY -> ASSETS_READY -> AUDIO_READY
     -> RENDERED -> QUALITY_CHECKED -> AWAITING_APPROVAL -> APPROVED -> PUBLISHED
```

* Forward edges plus one-step rework edges are defined in
  `midnight_archive/database.py::TRANSITIONS`.
* `APPROVED` and `PUBLISHED` are terminal.
* A stage command checks the current status before writing anything.

## Handoff contracts

| Artifact | Producer | JSON Schema | CLI |
|---|---|---|---|
| Idea batch | Agent 1 | `schemas/idea_session.schema.json` | `ideas` |
| Script | Agent 2/3 | `schemas/script.schema.json` | `import-script` |
| Storyboard | Agent 4 | `schemas/storyboard.schema.json` | `import-storyboard` |
| Asset plan/manifest | Phase 2 | `schemas/asset_manifest.schema.json` | `assets` |
| Narration + word timings | Phase 2 | `schemas/narration_metadata.schema.json` | `narrate` |
| Render record | Phase 2 | `schemas/render_metadata.schema.json` | `render` |
| Technical QC | Phase 2 | `schemas/technical_report.schema.json` | `qc-check` |
| Creative QC report | Agent 8 | `schemas/quality_report.schema.json` | `qc` |

All models are in `midnight_archive/models.py` with `extra="forbid"`. Do not
loosen them to make a handoff pass; fix the handoff.

Artifacts are written to `output/scripts/`, `output/storyboards/`,
`output/asset_plan/`, `output/narration_metadata/`, `output/render_metadata/`,
`output/technical_qc/` and `output/qc/` as `<video-id>-<slug>-v<n>.json`, and
hashed into SQLite. Media lives under `output/drafts/<video-id>/` and
`output/rendered/`. Reruns create new versions; never overwrite a committed
artifact.

## Agent roles

* [agents/researcher.md](agents/researcher.md) - Agent 1, ideation
* [agents/story_architect.md](agents/story_architect.md) - Agent 2, story
* [agents/script_editor.md](agents/script_editor.md) - Agent 3, editing gates
* [agents/storyboard.md](agents/storyboard.md) - Agent 4, scene plan
* [agents/visual_producer.md](agents/visual_producer.md) - Agent 5, Phase 2
* [agents/audio_producer.md](agents/audio_producer.md) - Agent 6, Phase 3
* [agents/quality_control.md](agents/quality_control.md) - Agent 8, final gate

## Code conventions

* Python 3.11+ syntax, full type hints, `pathlib.Path`, UTF-8 everywhere.
* Never talk to SQLite outside `midnight_archive/database.py`.
* Never parse YAML outside `midnight_archive/config.py`.
* Handoff data enters through Pydantic models; no raw dicts in business logic.
* New runtime dependencies need a free/open-source licence and a line in
  `requirements.txt`. Prefer the standard library.
* Keep Windows compatibility: no POSIX-only shell calls, no `/tmp` paths.
* Tests must not touch `data/`, `output/` or the network. Use the `project`
  fixture, which builds an isolated project in `tmp_path`. Phase 2 media tests
  may read the local voice/font/model assets, but all generated audio, images,
  renders and FFmpeg work files go under `tmp_path`.

## Definition of done for a stage

1. The command validates input and refuses to run from the wrong status.
2. It writes a versioned artifact and records a status event.
3. It is idempotent for identical input (job key replay).
4. It has a test for the success path and at least one refusal path.
5. `python -m pytest` passes.
6. The README command list still matches reality.
7. For a rendered video, `qc-check` passes before any creative QC report is
   recorded. A passing technical file must never be given creative points
   automatically; author the creative report separately.

## Content quality bar

A script must be 90-130 spoken words, 35-60 seconds at 2.5 words/second, open
on the impossible detail, contain a causal chain the viewer can follow, and end
on a line under 12 words that reframes the opening. The QC gate is 80/100.


## Sharing archive and new workspaces

This checkout preserves previous production versions. For a NEW story, use
scripts/create_workspace.py to create a clean sibling workspace before init/new/import.
Read docs/AGENT_START_HERE.md and docs/PRODUCTION_GUIDE.md. Never run archived
TMA-0001 one-off scripts against another story or assume historical absolute paths
are portable. Use the actual CLI-returned video ID.

The sharing copy uses Git LFS for model/font/image/audio/video binaries. Preserve
.gitattributes and licence notices. Never commit .env, credentials, private chats,
virtual environments, download caches, runtime logs or the live production database.
No paid service, release approval or automatic publishing is implied by Git sharing.

The generic assets command makes Pillow placeholders. The polished example's custom
visual manifest and approved-WAV import are not general CLI integrations. New custom
production must validate explicit inputs and refuse overwrites. Shared source modules
must have one technical owner at a time; do not concurrently edit them.
