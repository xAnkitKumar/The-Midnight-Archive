# Agent 8 - Final Quality Control

## Mission

Score the finished video out of 100 and reject anything below 80 or carrying a
serious factual, copyright, audio or visual defect. This gate is separate from
human approval: passing QC does not approve a video.

## Inputs

* The rendered MP4 in `output/rendered/`, the SRT, the script and storyboard.
* Watch the video once with sound, once muted, once on a phone-sized window.

## Output

A `QualityReport` matching `schemas/quality_report.schema.json`:

```json
{
  "video_id": "TMA-0001",
  "reviewer": "owner",
  "scores": {
    "hook": 13, "originality": 9, "coherence": 14, "suspense": 13,
    "ending": 14, "voice": 8, "visual_consistency": 9,
    "subtitle_sync": 5, "audio_mix": 4
  },
  "blocking_issues": [],
  "notes": "Watched on phone, sound on."
}
```

## Rubric

| Criterion | Max | What is measured |
|---|---|---|
| First-two-second hook | 15 | Does the impossible detail land before a thumb can scroll? |
| Originality | 10 | Specific rule and payoff, not a genre mood |
| Narrative coherence | 15 | Causal chain, continuity, no cheat |
| Suspense | 15 | Escalation, withheld information, pacing |
| Ending | 15 | Earned reframe; final line lands |
| Voice | 10 | Natural, expressive, consistent level |
| Visual consistency | 10 | Characters, palette, lighting, no broken frames |
| Subtitle synchronisation | 5 | Cues match speech within ~120 ms |
| Audio mix | 5 | Narration intelligible, music ducked, no clipping |

## Rejection

* Total below 80.
* Any `blocking_issues` entry (factual claim presented as science, copyright
  concern, missing licence, clipped audio, desynced subtitles, broken frame).
* Silence or a missing voice track is always blocking, regardless of score.

Record blocking issues as short, specific sentences. "Bad audio" is not
actionable; "music masks the final line from 00:48 to 00:52" is.

## Commands

```powershell
.\.venv\Scripts\python.exe -m midnight_archive qc --video TMA-0001 --file output\drafts\TMA-0001-qc.json
```

A pass moves the video to `AWAITING_APPROVAL`. The owner then runs `approve`;
the studio never publishes on its own.
