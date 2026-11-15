from pathlib import Path
import sys,json,hashlib,shutil
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from midnight_archive.config import Settings
from midnight_archive.database import Database
s=Settings.load(ROOT);db=Database(s.db_path)
out=ROOT/"output/drafts/TMA-0001/test-render-v1"
meta=json.loads((out/"render-metadata-v1.json").read_text())
verify=json.loads((out/"verification-v1.json").read_text())
qc=json.loads((out/"technical-qc-v1.json").read_text())
audio_sha=verify["approved_narration_sha256"];video_sha=verify["output_mp4_sha256"]
scene_lines="\n".join(f"| {x['scene']} | {x['start']:.3f} | {x['end']:.3f} | {x['end']-x['start']:.3f} |" for x in meta["scene_timings"])
report=f"""# TMA-0001 v3 - First full test render
Prepared 15 November 2026. Human review only.

The preview is complete and passes all 31 technical QC checks. It has not been creatively approved, approved for release, or published. Project state is RENDERED. No creative score was invented or recorded.

## Watch and inspect
- TMA-0001-v3-approved-v4-test-preview.mp4: 55.200 seconds, 1080 x 1920, 30 fps, H.264/yuv420p, AAC stereo at 48 kHz, 21.43 MB.
- technical-qc-v1.json: all 31 checks pass, including full decode, duration, dimensions, frame rate, audio, silence/black intervals, subtitle text and coverage.
- verification-v1.json: artifact preservation and narration hashes, overwrite refusal, tests and additional loudness measurement.
- review-frames/encoded-contact-sheet.jpg: sampled frames decoded from the completed MP4.
- audio/subtitles-v2.srt and audio/subtitles-v2.ass: final subtitles for this preview. Earlier v1 preparation files are retained for traceability but are not used.
- audio/alignment-v2.json: fresh word timing and recognition audit.
- storyboard-aligned-v1.json: the ten original scenes with revised timings.
- provenance/asset-manifest-v1.json: visuals and original sound asset sources and hashes.

## Approved narration and timing
Kokoro-82M, bm_george, British English, speed 0.96. The approved narration v4 is 55.19725 seconds at 24 kHz mono. Its production import is byte-identical to the approved source. No TTS was invoked, no words changed, and no pacing, pitch, silence or pronunciation was edited.

Narration SHA-256: {audio_sha}

For the stereo mix only, the original was resampled to 48 kHz and placed equally in both channels at 0 dB gain. The narrator was not compressed, limited or time-stretched. Container duration rounds to 55.200 seconds at 30 fps.

Fresh faster-whisper base.en/int8 alignment covers all 129 displayed tokens. Spoken time forms were mapped back to displayed 3:07 and 2:40. All other tokens align directly except the two tokens Mara Kwan, which are interpolated because recognition merges them as Maraquan. This does not establish that pronunciation is wrong, and no correction was made to the approved recording.

There are 31 subtitle cues. Sentence and beat boundaries are respected even for one-word reveals; suspense subtitles do not run into the next sentence. Source narration pauses are unchanged, including those after "He was alive.", "Different name." and "His name. Mara's."

The source script remains v3. The production storyboard was saved as v4 with timing changes only; all original creative fields and the ten-scene structure are preserved. Scene boundaries are placed 80 ms before the next scene's first aligned word.

| Scene | Start (s) | End (s) | Duration (s) |
|---|---:|---:|---:|
{scene_lines}

## Visual execution
Eleven generated 9:16 stills support ten logical scenes, including a second angle within the opening at approximately 5.13 seconds. This preserves the opening obituary close-up while avoiding a single ten-second hold. A common scene-4 character reference was used for Elias and Mara. Wardrobe, amber practical lighting, teal shadows and grain are consistent in the inspected frames.

The first frame shows the obituary, with a small 22%-opacity wordmark at the top. There is no logo intro or end card. Camera drift is limited to 1.8%; transitions are brief dissolves rather than vertical push effects. No black fade obscures the opening. The end fades over the last 0.6 seconds, after the spoken ending.

The critical printed clues are readable in inspected full-resolution frames: Elias Voss / 4B / 3:07 A.M.; ONE NAME PER FIRE; Mara Kwan / 4A / ENTERED 4B TO WARN OCCUPANT. Scene 9 contains exactly two obituary sheets. The corridor's unintended extra heater was removed, and the stairwell pose was corrected to show Elias descending without looking back. Original generated variants remain in their original locations.

## Audio execution
The score and effects are generated locally from tones and shaped noise, without external music recordings or stock samples. The score sits at -26 dB gain with up to roughly 6.94 dB additional ducking during speech. The piano/score fades out at Mara's reveal (39.125 seconds), leaving a quiet low room drone.

Effects are sparse: paper movements, soft knocks, electrical clicks, rain and a distant siren. There are no loud booms or exaggerated horror stingers. Exact event times and gains are in audio/mix-plan-v1.json; individual stems are preserved.

Measured final AAC decode: -14.66 LUFS integrated, -1.49 dBTP, loudness range 2.10 LU. The additional FFmpeg loudnorm run was measurement to a null sink only; its output_* values are hypothetical filtered values, not a second processed deliverable. Technical QC reports -1.5 dBFS sample peak, -17.3 dBFS mean, no unexpected black intervals, no unexpected silent sections and a clean full decode.

## Creative review needed
1. **Ending location continuity (44.45-55.20 s).** The finalized v3 storyboard places scenes 9 and 10 in 4B after the fire, while scene 10 also describes light from a burning building outside. The preview retains the authored scene descriptions and uses tight framing, but the move from the hotel back to 4B is not explicitly established. Freebuff/human review should decide whether that ambiguity reads as intentional. No script/location rewrite was made.
2. **Motion style and pacing.** These are generated photographic stills with modest camera moves, not animated performances. Sparks, smoke and characters do not animate independently. The front-desk scene lasts 6.51 seconds through the three short reveals. Judge whether that held composition and the overall still-image style provide enough cinematic movement.
3. **Newspaper continuity.** The essential names, apartments, time and warning are readable, and exactly two editions appear together. The large typography, heavily aged stock, 17 November 1978 date and layout variation between macro and overhead shots need art-direction review. Those choices are in the visuals, not additions to the spoken script.
4. **Narration in context.** The approved voice is unchanged. Listen to Elias and Mara Kwan within the finished mix and judge music/effect restraint on headphones and a phone speaker. ASR still merges Mara's name. Automated checks are not a human listening test.
5. **Small-screen legibility.** Check the low-opacity top wordmark, bottom safe-area captions and the scene-8 warning on the actual viewing device. Frame inspection found readable critical text and no caption overlap with the main printed clues.

No human listening test or final creative approval is claimed. Technical success alone is not release approval.

## Implementation, validation and preservation
The isolated orchestration lives in provenance/orchestration/. The shared voiceover, audio, renderer and subtitle modules and configuration were left unchanged. The renderer is subclassed only inside the preview script to remove the opening fade, cap thread usage, add the opening reverse angle and restrain transitions. No production narration defaults or dependencies changed, and no shared-branch commit was made.

The existing suite completed successfully: 80 tests, exit 0. It includes real short-render/technical-QC, subtitle round-trip and missing-word alignment checks, state guards and job replay tests. The finished preview passed 31/31 QC checks. The renderer's overwrite refusal was exercised against the existing preview and stopped before encoding; its hash remained unchanged.

All 103 tracked pre-existing code/config/test, script, storyboard, narration and MP4 files retained their hashes. Prior production MP4 versions v1/v2 are preserved; this preview is production MP4 v3. Source script versions and narration versions are untouched. State transitions were STORYBOARD_READY -> ASSETS_READY -> AUDIO_READY -> RENDERED, with versioned artifacts registered through Database.

Preview visuals/audio are registered under preview_image / preview_audio, and this render uses the explicit versioned manifest. The generic production CLI still selects legacy image assets; do not assume a future CLI rerender will automatically select this preview's images. Manifest-scoped selection should be integrated in a separate authorized production change if this visual set is accepted. The preview driver refuses another full render in this package.

Two preparation/reporting issues were fixed without re-encoding: a required beat-duration metadata field and FFmpeg JSON followed by log text. Early subtitle grouping was improved in a new v2 file. None altered the approved WAV.

Existing licensing records identify Kokoro-82M/model voices as Apache-2.0 and kokoro-onnx as MIT. Visuals were generated through the built-in image tool using original fictional characters and internal references; the manifest records generated-output provenance rather than assigning them a stock/open-source licence. Music and SFX are original procedural production audio. No external stock purchase or paid API integration was used.

Preview MP4 SHA-256: {video_sha}

Human review remains the next gate. This package does not authorize publishing or release approval.
"""
(out/"creative-review-v1.md").open("x",encoding="utf-8").write(report)
shutil.copy2(ROOT/"work/test-render-v1/finalize_verification.py",out/"provenance/orchestration/finalize_verification.py")
for kind,p in [("creative_review_draft",out/"creative-review-v1.md"),("render_verification",out/"verification-v1.json")]:
 db.add_artifact("TMA-0001",kind,db.next_artifact_version("TMA-0001",kind),s.relative(p),hashlib.sha256(p.read_bytes()).hexdigest())
dest=Path(r"C:\Users\LOQ\Documents\Codex\2026-11-15\c-users-loq-config-freebuff-desktop\outputs\TMA-0001-v3-test-render-1")
assert not dest.exists()
shutil.copytree(out,dest)
source_video=ROOT/meta["mp4_path"];target=dest/"TMA-0001-v3-approved-v4-test-preview.mp4"
shutil.copy2(source_video,target)
assert hashlib.sha256(target.read_bytes()).hexdigest()==video_sha
deliverables={p.relative_to(dest).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob("*") if p.is_file()}
(dest/"package-sha256.json").open("x",encoding="utf-8").write(json.dumps(deliverables,indent=2))
print("DELIVERED",dest)
print("FILES",len(deliverables),"MP4",target.stat().st_size)
print("STATE",db.require_video("TMA-0001")["status"])
