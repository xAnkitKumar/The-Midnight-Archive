# The Midnight Archive

A local Python studio for original cinematic mystery, psychological horror and mind-bending short stories. Your creative agent writes the story and storyboard; Python validates the handoffs, versions the artifacts, generates speech, aligns subtitles, mixes audio and renders vertical video.

**New here?** For a one-page model handoff, read [HANDOFF.md](HANDOFF.md). Then start with [a clean story workspace](#start-a-new-story-workspace), and give your agent the [starter prompt](docs/AGENT_START_HERE.md). Do not run new production jobs inside this historical archive checkout.

## What is included

- Python application, configuration, seven creative role contracts, JSON Schemas and automated tests.
- Every available TMA-0001 script/storyboard version, narration audition and review candidate, generated visual, sound stem, subtitle file, MP4 and QC report.
- Kokoro ONNX model/voice pack, optional Piper voice and Montserrat font, with notices. Large files are stored using Git LFS.
- Read-only database records, original documentation and experimental scripts for provenance. Local environments, caches, secrets and private agent chats are excluded.

This repository was created from the existing project snapshot. Its initial Git commit preserves the available versioned files; it does not invent earlier Git commit history.

## Current reviewed example

TMA-0001: **The Man Who Received Tomorrow's Newspaper**.

| Item | Selected artifact |
|---|---|
| Creative script | [v3, 129 words](output/scripts/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v3.json) |
| Creative storyboard | [v3, ten scenes](output/storyboards/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v3.json) |
| Actual narration timings | [storyboard v4](output/storyboards/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v4.json), creative fields unchanged |
| Approved narration | [v4 WAV](output/drafts/TMA-0001/test-render-v1/audio/approved-narration-v4.wav), Kokoro bm_george, British English, speed 0.96, 55.19725 s |
| Full test preview | [MP4 v3](output/rendered/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v3.mp4), 55.20 s, 1080x1920, 30 fps |
| Technical QC | [31/31 checks passed](output/drafts/TMA-0001/test-render-v1/technical-qc-v1.json) |
| Creative review | [Review report and remaining issues](output/drafts/TMA-0001/test-render-v1/creative-review-v1.md) |

The narration is human-approved; the full video is **RENDERED, awaiting human review**, not approved for publishing. Earlier MP4s use older creative versions. Do not confuse a passing historical QC report with current release approval.

The polished preview uses eleven generated stills for ten logical scenes, an opening reverse angle, restrained motion, fresh word alignment and a separate original mix. The generic CLI creates deterministic Pillow placeholders. Built-in chat image generation is **not an integrated Python provider**. See [production limitations](docs/PRODUCTION_GUIDE.md).

## Clone the archive

Install Git and Git LFS, then:

~~~powershell
git lfs install
git clone https://github.com/xAnkitKumar/The-Midnight-Archive.git
cd The-Midnight-Archive
git lfs pull
git lfs fsck
~~~

This repository is public. A complete checkout contains roughly 826 MB before Git metadata. Public access does not grant reuse rights to the project's original code, stories or artwork; see [Licensing and access](#licensing-and-access). If an ONNX, WAV or MP4 opens as a short text file starting with "version https://git-lfs.github.com/spec/v1", run git lfs pull.

For a smaller source-only checkout, set GIT_LFS_SKIP_SMUDGE=1 while cloning, then fetch the assets needed for production:

~~~powershell
git lfs pull --include="assets/tts/**,assets/voices/**,assets/fonts/**"
~~~

The archived video can be fetched separately:

~~~powershell
git lfs pull --include="output/rendered/*-v3.mp4"
~~~

## Start a new story workspace

Python **3.12** and FFmpeg/ffprobe are the tested Windows setup. FFmpeg must support libx264, AAC, libass, xfade and zoompan. Story/script development works without the media models or FFmpeg; full media production needs them.

From the clone, create an empty sibling workspace. This copies reusable code, configuration, schemas, agent contracts and available runtime model/font assets. It copies no old stories, production outputs, live database, environment files or asset registry.

~~~powershell
py -3.12 scripts/create_workspace.py --destination ../My-Story-Studio
cd ../My-Story-Studio
powershell -ExecutionPolicy Bypass -File ./scripts/setup.ps1
.\.venv\Scripts\python.exe -m midnight_archive doctor
.\.venv\Scripts\python.exe -m pytest
~~~

The helper refuses an existing destination, a nested destination inside the archive, and unresolved LFS pointer files. Use --skip-media when only drafting scripts. The setup script creates a new local SQLite database. It does not copy the archived job state.

FFmpeg can be installed on Windows with:

~~~powershell
winget install --id Gyan.FFmpeg -e --scope user
~~~

Open a new terminal afterward. If the Python launcher is unavailable, install Python 3.12 or use uv to create an environment. Never copy the source machine's virtual environment.

The saved [environment package inventory](docs/environment-packages.json) is an audit of the tested machine, not a portable replacement for requirements.txt. The Chatterbox experiment has separate dependencies and must stay in a separate environment.

## Make another story with your agent

Copy the complete prompt in [AGENT_START_HERE.md](docs/AGENT_START_HERE.md) into Codex, Freebuff or another coding/creative agent with access to the new workspace.

The agent should:

1. Read AGENTS.md, config/brand.yaml and the role contracts.
2. Develop a new premise with the user; register it through the CLI and use the returned video ID.
3. Write natural spoken English, 90-130 words, targeting 45-60 seconds. Preserve short emphasis at important reveals.
4. Validate and import a versioned script, then a storyboard covering every narration word exactly once.
5. Get creative and voice-sample review before generating all final assets.
6. Render only when authorized, run technical QC, and wait for human review. Never publish automatically.

The application does **not** ask an LLM to write a full script automatically. The free offline idea generator supplies starting concepts; your agent does the creative writing.

### Register a concept

Run this in the new workspace:

~~~powershell
.\.venv\Scripts\python.exe -m midnight_archive new --title "Your Original Title" --category mystery --premise "A concrete original premise of at least twenty characters." --select
~~~

Use the actual ID printed by that command, not a guessed ID:

~~~powershell
$videoId = "TMA-0001" # replace with the ID returned in YOUR new workspace
.\.venv\Scripts\python.exe -m midnight_archive show --video $videoId --json
.\.venv\Scripts\python.exe -m midnight_archive import-script --video $videoId --file output/drafts/my-script-v1.json
.\.venv\Scripts\python.exe -m midnight_archive review --video $videoId --json
.\.venv\Scripts\python.exe -m midnight_archive import-storyboard --video $videoId --file output/drafts/my-storyboard-v1.json
~~~

Choose category mystery, psychological_horror or mind_bending. The JSON must match schemas/script.schema.json and schemas/storyboard.schema.json. samples/demo_script.json and samples/demo_storyboard.json are valid **older format examples**, not the current approved story and not permission to reuse its plot.

For offline ideas instead:

~~~powershell
.\.venv\Scripts\python.exe -m midnight_archive ideas --count 15 --seed 20261115 --label "new story session"
.\.venv\Scripts\python.exe -m midnight_archive ideas --list
.\.venv\Scripts\python.exe -m midnight_archive select --idea IDEA-0001
~~~

Replace the idea ID with one actually returned.

## How the pipeline works

~~~text
Creative agent
  -> strict Script JSON -> import-script
  -> strict Storyboard JSON -> import-storyboard
  -> licensed assets -> narration WAV -> word alignment -> SRT/ASS
  -> music/SFX mix -> FFmpeg MP4 -> technical QC
  -> separate creative review -> explicit human approval -> manual publication
~~~

| Component | Responsibility |
|---|---|
| midnight_archive/models.py | Strict Pydantic contracts; unknown fields rejected |
| config.py + config/*.yaml | Validated configuration and brand direction |
| database.py | SQLite state, jobs, replay guards, audit trail and artifact records |
| pipeline.py | Stage orchestration, versioned files, state and approval guards |
| script_editor.py / storyboard.py | Editorial checks, timing and word coverage |
| voiceover.py | Kokoro default, optional Piper fallback; voice provenance |
| subtitles.py | faster-whisper word timestamps mapped to authored words |
| asset_manager.py / licensing.py | Asset sources, hashes and commercial-use checks |
| procedural_audio.py / visuals.py | Original procedural audio and placeholder stills |
| renderer.py / technical_qc.py | 9:16 encoding, FFprobe/FFmpeg verification |
| agents/ | Role instructions, not background autonomous services |
| experiments/ | Isolated voice comparisons; not production defaults |

State flow:

~~~text
IDEA -> SELECTED -> SCRIPTED -> STORYBOARD_READY -> ASSETS_READY -> AUDIO_READY
     -> RENDERED -> QUALITY_CHECKED -> AWAITING_APPROVAL -> APPROVED -> PUBLISHED
~~~

APPROVED and PUBLISHED are terminal. Changed scripts are versioned; earlier files are preserved. Do not edit SQLite manually or force a state to bypass a failed stage.

## Commands and gates

All examples use the workspace's venv Python. Global --root and --verbose options go before the command.

| Command | Result |
|---|---|
| init / doctor | Create runtime folders/schema; inspect environment |
| new / ideas / select | Register a concept |
| import-script / review | Validate script and inspect automatic preflight |
| import-storyboard | Validate scene timing and exact narration coverage |
| assets | Generate/register procedural placeholders, score, SFX, font and voice |
| narrate | Generate full narration, fresh alignment, subtitles and mix |
| render | Create a versioned MP4 from AUDIO_READY |
| produce | Run assets, narration and render; stops at RENDERED |
| qc-check | Inspect the actual MP4, independent of creative scoring |
| qc | Record a separate creative report; requires technical pass |
| approve | Record explicit human release approval |
| publish | Record a publication already performed manually; does not upload |
| show / list / stats | Inspect state or record manual performance |
| export-schemas | Regenerate JSON Schemas from the models |

Do not run narrate/produce for an already approved recording. The CLI has no general-purpose "import this approved WAV" command; the example used isolated import orchestration. A new approved-audio import must preserve its bytes and provenance, validate state, and generate new alignment.

See [the production guide](docs/PRODUCTION_GUIDE.md) for the exact approval-gated media sequence and known integration gaps.

## Archive and reproducibility

- output/: historical versioned creative and media artifacts, including previous MP4s.
- archive/database-records.json: read-only API export of videos, events, ideas, jobs and related records.
- archive/source-file-manifest.json: hashes and original-to-shared file mapping.
- archive/work/: retained experiment sources and outputs; caches/environments omitted.
- docs/history/: original README, AGENTS and gitignore, retained without erasing history.
- assets/: model/font files and original media with source records.
- licenses/: third-party notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Historical audit files and one-off scripts contain original machine paths. They are provenance, not portable commands. Do not run archived TMA-0001 production scripts against a new story. Fresh workspaces deliberately begin with a new database and registry.

## Licensing and access

Kokoro model/voices are Apache-2.0; kokoro-onnx is MIT. The Piper engine is GPL-3.0 and its voice/data provenance is separate. Montserrat is SIL OFL 1.1. Exact upstream sources and notices are retained in THIRD_PARTY_NOTICES.md.

No blanket open-source licence has been chosen for the project's original code, stories or generated artwork. Repository access and reuse permissions remain with the owner; third-party licences do not automatically license the entire project. No secrets, private chats or credentials are included.

## Verification

The original full test suite passed 80 tests. This sharing version passes 86 tests (80 existing plus 6 safe-workspace tests); the verification record is in docs/sharing-verification.json. Media tests use temporary projects, may use local model/font files, and must never alter archived production output.

~~~powershell
.\.venv\Scripts\python.exe -m pytest
~~~

Human listening and creative review remain necessary even when all machine checks pass.
