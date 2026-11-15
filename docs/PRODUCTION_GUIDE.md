# Production guide for another story

## 1. Reusable application versus historical demo

The generic application is in midnight_archive/. It handles arbitrary video IDs and validated stories. The final TMA-0001 image set and approved-audio import were implemented through isolated orchestration, whose source is retained in output/drafts/TMA-0001/test-render-v1/provenance/orchestration/ and archive/work/.

Those scripts contain specific source hashes, TMA-0001 paths, scene mapping and one-render guards. They are not a reusable "make any story" command. Never blindly replace a video ID and execute them.

The original production database is deliberately not distributed as an active database. archive/database-records.json is a read-only record export. Create a clean workspace so a new local TMA-0001 cannot collide with archived TMA-0001 output filenames.

## 2. Script and storyboard contracts

The runtime models are authoritative: midnight_archive/models.py. JSON Schemas are under schemas/. Unknown fields are refused.

Script:
- schema_version, video_id, title, category, logline, source, narration, final_line, optional visual_style/content_notes/claims.
- Source: original or public_domain_adaptation; an adaptation requires reference and public_domain true.
- Beats: consecutive beat number, text, pause_after_ms (0-2000).
- final_line must exactly match the complete last beat text.
- The validator checks 90-130 words, estimated 35-60 seconds, banned phrasing and editorial issues. For this channel aim for 45-60 seconds.
- Automatic preflight is editorial assistance, not human approval.
- Avoid writing every ordinary sentence as a separately announced fragment or putting an identical long pause after every beat.

Storyboard:
- schema_version, video_id, style_bible, music and consecutive scenes.
- Each scene requires start/end, narration, visual, characters, environment, lighting, camera, on_screen_text, sfx, transition and image_prompt.
- Timeline starts at zero and is contiguous. Each scene must cover its assigned narration exactly; concatenate scene narration to recover the script.
- Initial timings can use words / 2.5 + scripted pause seconds; final timings must come from the recorded narration.
- Explicitly establish where characters move, what causes the danger and how the protagonist learns the reveal.
- Plan paper/sign text as a legibility requirement and inspect the actual output; the original role contract's caution about generated lettering remains useful.

Save drafts with fresh version suffixes. Import commands validate and create immutable versioned artifacts. Use the actual CLI-returned video ID in both JSON files.

## 3. Narration and sample review

The shared default is Kokoro bm_george, speed 0.96, en-gb. Kokoro runs on CPU ONNX in the tested setup; an RTX GPU is not required for this path. Piper remains optional.

The standard narrate command synthesizes a full script per beat. It is not an audition-only or approved-WAV import command. For a sample, use an isolated experiment under experiments/ or a new review-only directory and keep it outside production state transitions. Read the experiment's --help; do not assume the original voice-lab supports Kokoro simply because production does.

A sample should cover ordinary exposition and a reveal. Compare candidates at matched loudness with one consistent identity, preserve model/voice hashes and settings, and wait for listening approval. ASR checks words, not naturalness.

The improved TMA-0001 narration joined connected exposition into six longer passages and shortened ordinary boundary gaps while protecting three intentional suspense pauses. Its timing decisions are story-specific, not universal constants.

Once a WAV is approved:
- Copy it to a new versioned production path and verify identical SHA-256.
- Record provider, voice, licence, source/version and measured duration.
- Align the actual WAV. Never regenerate narration to obtain convenient timings.
- Keep displayed text canonical. Spoken "three-oh-seven" can map to displayed 3:07 without rewriting the script.
- Disclose ASR interpolation or uncertain names. In the example, Mara Kwan was merged by ASR; spelling stayed unchanged.
- Do not stretch every word or increase global speed just to hit a target.

A general approved-WAV import CLI is still an integration gap. Technical agents must implement or adapt an isolated importer with status, hash and overwrite checks before using one for a new story.

## 4. Assets, licences and visuals

The standard assets command registers Kokoro/Piper and font assets, generates Pillow placeholder stills and original procedural score/SFX, and moves the video to ASSETS_READY.

Cinematic image generation in the example was performed through a chat image tool. There is no integrated image-generation service, API key or background worker in this repository. Another agent needs its own permitted image tool or licensed supplied images.

Use one character reference and fixed appearance descriptions, then inspect:
- identity and wardrobe continuity;
- geography, direction of travel and cause/effect;
- readable names, dates, apartment numbers and warnings;
- hands, faces and repeated props;
- safe areas for captions and subtle branding.

Record prompts, source paths, hashes, generator provenance and licence/terms. A model's software licence is not the artwork's licence. Never silently classify an unknown or non-commercial asset as commercial.

The default render command queries all assets with kind image for that video. The custom preview uses preview_image plus an explicit manifest to avoid mixing legacy and new image sets. A future reusable custom-asset path should resolve one versioned manifest; simply adding another ten image rows can cause a count mismatch or select the wrong version.

## 5. Authorized placeholder production

After creative and voice choices are reviewed, and only when full generation/rendering is authorized, the generic path is:

~~~powershell
$videoId = "ACTUAL-ID"
.\.venv\Scripts\python.exe -m midnight_archive assets --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive narrate --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive render --video $videoId
.\.venv\Scripts\python.exe -m midnight_archive qc-check --video $videoId --json
~~~

This path generates new full narration and placeholder art. It must not be used to replace an approved WAV or custom visual set. produce combines the first three stages and stops at RENDERED; it is unsuitable when a human gate is required between them.

For custom production, resolve the approved audio and explicit image manifest, generate fresh alignment/subtitles, update timing-only storyboard fields, mix restrained original/licensed music and SFX, and invoke the renderer with those specific inputs. Preserve old versions and use Database APIs for registration/state.

## 6. Tests and review

Run the test suite before handing off implementation changes. Existing tests exercise temporary projects and include a real short render/full decode when local media requirements are available.

Technical QC checks format, size, timing, codec, audio levels, silence/black intervals, subtitle text/coverage and decode integrity. It does not judge realism, emotional delivery, plot clarity or licensing.

A creative report should identify remaining problems and state which checks were actually performed. Do not claim listening based on ASR or video viewing based only on metadata. Human review must inspect the MP4 with sound on a phone and headphones.

qc records a separate scored creative report after technical QC. approve records explicit human approval; publish records a manual publication URL. Neither should be run automatically by an agent.

## 7. Environment and recovery

- Missing modules: use the workspace's .venv interpreter and requirements.txt.
- Missing model or tiny model file: run git lfs pull in the clone before making the workspace.
- Missing whisper model: first alignment downloads base.en to the user's cache; later runs can use the cache offline.
- Missing FFmpeg/libass: install a build with the required codecs/filters; inspect doctor.
- Wrong status: inspect show and the audit trail. Do not alter SQLite directly. Rework must follow the documented state machine.
- Changed import: the identical input replays; a revised input creates another version where the stage allows revisions.
- Existing destination: create_workspace refuses to overwrite anything; choose a new directory.
- Preview-only scope: do not infer approval to rerender, regenerate narration or publish.

Original reports under docs/history and earlier output versions may describe superseded milestones. The current README and the latest artifact-specific review identify the selected example.
