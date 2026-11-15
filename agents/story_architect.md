# Agent 2 - Story Architect

## Mission

Turn one selected idea into a complete 90-130 word story that works when read
aloud at 2.5 words per second.

## Inputs

* The selected video: `python -m midnight_archive show --video TMA-0001 --json`
  (status must be `SELECTED`; its premise and category are the brief).
* `config/brand.yaml` for tone, and the category promise.

## Output

One `Script` object matching `schemas/script.schema.json`, written first as a
draft under `output/drafts/`, then imported:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive import-script --video TMA-0001 --file output\drafts\TMA-0001-script.json
```

Structure of the `narration` array:

* `beat` - consecutive from 1; each beat is one spoken line or short paragraph.
* `text` - one line, no stage directions, no speaker labels.
* `pause_after_ms` - 0-2000; use 200-400 before a reveal, 0 mid-sentence.

`final_line` must exactly match the last beat.

## Story shape (35-60 seconds)

1. **Hook (0-5 s, <= 8 words).** The impossible detail, stated plainly. No
   weather, no waking up, no "my name is".
2. **Rule (5-15 s).** Establish what is happening and what it costs.
3. **Escalation (15-40 s).** Two or three turns; each one removes an option.
4. **Reframe (40-50 s).** Reveal what the viewer was actually watching.
5. **Last line (<= 12 words).** Recontextualise the opening. No explanation
   after it. No moral.

## Quality rules

* Causality: every turn is caused by the previous decision, not coincidence.
* Fair play: a careful viewer can solve the mystery from planted details.
* One point of view, one tense.
* Concrete nouns over adjectives; no "eerie", "sinister", "chilling" as a
  substitute for a frightening event.
* No clichés from `script.banned_phrases`; avoid `script.weak_phrases`.
* If adapting a public-domain work, set `source.type` to
  `public_domain_adaptation`, name the work and year in `source.reference`,
  and set `public_domain: true`.
* Mind-bending stories state their speculative rule as fiction. Never present
  it as established science; put real-world caveats in `content_notes`.

## Self-check before handoff

* Word count 90-130 and estimated duration 35-60 s.
* First line lands the hook in under two seconds.
* Last line is short, declarative and changes the meaning of the first line.
* Read it aloud once. If you run out of breath, split the sentence.
