# Model handoff: continue The Midnight Archive

- **Repository:** <https://github.com/xAnkitKumar/The-Midnight-Archive>
- **Current branch:** `main`
- **Current example:** TMA-0001, *The Man Who Received Tomorrow's Newspaper*
- **Current state:** `RENDERED` — awaiting human creative review. **Not approved and not published.**

This repository is the historical archive and a reusable Python studio. Read these first, in order:

1. [README.md](README.md)
2. [AGENTS.md](AGENTS.md)
3. [docs/AGENT_START_HERE.md](docs/AGENT_START_HERE.md) — the complete prompt to give a creative agent
4. [docs/PRODUCTION_GUIDE.md](docs/PRODUCTION_GUIDE.md) — contracts, media sequence and known gaps
5. `config/brand.yaml`, `config/settings.yaml`, and the role contracts under `agents/`

## Do not start a new story in this checkout

This checkout preserves TMA-0001 and its version history. Create a clean sibling workspace before registering or producing a new video:

```powershell
git lfs install
git lfs pull
py -3.12 scripts/create_workspace.py --destination ../My-Story-Studio
cd ../My-Story-Studio
powershell -ExecutionPolicy Bypass -File ./scripts/setup.ps1
.\.venv\Scripts\python.exe -m midnight_archive doctor
.\.venv\Scripts\python.exe -m pytest
```

`create_workspace.py` copies code, configuration, schemas, agent contracts and available model/font assets. It deliberately copies no old stories, production outputs, live database or asset registry. Use `--skip-media` if you only need to draft scripts.

A full clone is roughly 826 MB before Git metadata. If an ONNX, WAV or MP4 is a ~130-byte text file beginning with `version https://git-lfs.github.com/spec/v1`, run `git lfs pull` (or fetch only the needed paths).

## Current TMA-0001 facts

| Item | Value |
|---|---|
| Script | v3, 129 words, 10 scenes |
| Approved narration | v4 WAV, Kokoro `bm_george`, `en-gb`, speed 0.96, **55.19725 s** |
| Test preview | [MP4 v3](output/rendered/TMA-0001-the-man-who-received-tomorrow-s-newspaper-v3.mp4), 55.20 s, 1080x1920, 30 fps |
| Technical QC | 31/31 checks passed — [report](output/drafts/TMA-0001/test-render-v1/technical-qc-v1.json) |
| Creative review | [Remaining issues](output/drafts/TMA-0001/test-render-v1/creative-review-v1.md) |
| Release status | `RENDERED`; no `approve`, no `publish` |

Important: an earlier full narration review was **59.838 s**. The MP4 uses the separate **55.197 s** approved narration v4. Do not claim an old QC report or the longer review covers the audio in the MP4.

The creative review still lists human-judgment issues: location continuity, limited motion on still images, newspaper continuity and pronunciation. Human listening and a phone/headphone review remain necessary.

## Start a new video

Use the actual ID returned by the CLI; never guess it:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive new --title "Your Original Title" --category mystery --premise "A concrete original premise of at least twenty characters." --select
$videoId = "TMA-0001" # replace with the ID printed in YOUR workspace
.\.venv\Scripts\python.exe -m midnight_archive show --video $videoId --json
.\.venv\Scripts\python.exe -m midnight_archive import-script --video $videoId --file output/drafts/my-script-v1.json
.\.venv\Scripts\python.exe -m midnight_archive review --video $videoId --json
.\.venv\Scripts\python.exe -m midnight_archive import-storyboard --video $videoId --file output/drafts/my-storyboard-v1.json
```

Write a 90–130 spoken-word script targeting 45–60 seconds. The last beat must exactly equal `final_line`. The storyboard needs contiguous timings starting at zero, and every narration word must appear exactly once. Validate against `schemas/script.schema.json` and `schemas/storyboard.schema.json`; fix the handoff rather than weakening Pydantic models.

After creative and voice approval, and only with explicit authorization to render:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive assets --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive narrate --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive render --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive qc-check --video $videoId --json
```

`produce` combines assets, narration and render but stops only at `RENDERED`; it removes the human gates between those stages, so do not use it when review is required between them.

## What is still not a reusable command

- **Image generation is not integrated.** The generic `assets` command creates deterministic Pillow placeholders. TMA-0001's polished stills came from a chat image tool and an explicit versioned image manifest. A new custom production needs its own permitted image tool, recorded prompts/hashes/provenance and an explicit manifest.
- **Approved-WAV import is not a general CLI feature.** Do not call `narrate` or `produce` if that would regenerate a WAV a human already approved. Preserve the approved WAV byte-for-byte, align that exact file, and implement a versioned importer if needed.
- **The archived TMA-0001 orchestration scripts are not portable.** They contain story-specific paths, hashes and guards. Never blindly replace a video ID and run them.
- **Publishing is manual.** `approve` records explicit human approval; `publish` records a publication already performed. Neither uploads anything.

## Voice, assets and licensing

Default narrator: Kokoro `bm_george`, British English, speed `0.96`. Do not change an approved voice or recording without permission.

- Kokoro model/voices: Apache-2.0.
- `kokoro-onnx`: MIT.
- Piper fallback: GPL-3.0, with separate voice provenance.
- Montserrat: SIL OFL 1.1.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`. Public repository access does **not** grant a blanket licence to the project's original code, stories or generated artwork.

## Non-negotiable gates

1. No automatic publishing and no inferred approval from a score, a passing QC report or silence.
2. Never modify an `APPROVED` or `PUBLISHED` video; create a new video instead.
3. Never overwrite a versioned artifact; add the next version.
4. No paid API, subscription or asset purchase without explicit owner approval.
5. No secrets, `.env` files, private chats, virtual environments or the live database in Git.
6. Keep technical QC and creative judgment separate.
7. Say what was actually tested, listened to or viewed; do not claim untested behaviour.

## Definition of done for implementation work

Run the test suite before committing:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Preserve Git LFS (`.gitattributes`) and licence notices. Do not create a release, change repository visibility, rewrite history or force-push without explicit owner authorization. For the current example, the next legitimate step is human review of MP4 v3 — not another automated render.
