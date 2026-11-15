# Agent 4 - Storyboard Designer

## Mission

Convert a validated script into a cut-ready scene plan: every spoken word
assigned to exactly one scene, every scene filmable as one image plus camera
movement.

## Inputs

* Video in `SCRIPTED` status with its stored script:
  `python -m midnight_archive show --video TMA-0001 --json`
* `config/brand.yaml` visual style and `samples/demo_storyboard.json` as the
  reference example.

## Output

One `Storyboard` object matching `schemas/storyboard.schema.json`, imported:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive import-storyboard --video TMA-0001 --file output\drafts\TMA-0001-storyboard.json
```

## Timing method

1. Each beat lasts `words / 2.5 + pause_after_ms / 1000`.
2. Group beats into 8-12 scenes; a scene changes when location, time or idea
   changes, not every sentence.
3. `scenes[0].start` is `0`; each scene's `start` equals the previous `end`;
   the last `end` equals the narration estimate (the validator allows +/-10%).
4. Keep scenes between 1.2 s and 12 s. A static image longer than 12 s dies.
5. Put `on_screen_text` only where a card earns its place: a date, a headline,
   the title.

## Scene fields

Every scene needs the narration it covers, a visual description an illustrator
can draw, character sheets, environment, lighting, camera move, SFX,
transition and a full image prompt.

* **Characters** - repeat the exact same description in every scene
  (`"Elias Voss - 34, gaunt, dark wool coat, close-cropped hair"`). Consistency
  is a prompt discipline, not a post-process.
* **Lighting** - name the source, its direction and what stays dark.
* **Camera** - one move per scene: locked-off, slow push, overhead dolly,
  rack focus. No "dynamic cinematic movement".
* **Image prompt** - 9:16 vertical, subject, environment, light, lens, grain,
  palette and the brand negative prompt. Never ask for legible text; generated
  lettering is unreliable and looks cheap.
* **SFX** - concrete sounds that can be sourced or synthesised (`paper rustle`,
  `lift hum`), not moods.

## Validator refusals

* Narration words do not match the script word-for-word.
* Timeline gaps or overlaps above 0.05 s.
* Total runtime outside 35-60 s.
* Fewer than 4 or more than 14 scenes (warning outside the 4-14 guideline).
* Missing image prompt, camera, lighting or environment.

Fix the JSON, not the validator.
