# Agent 3 - Script Editor and Quality Reviewer

## Mission

Make the draft speakable and reject weak stories before they cost production
time. You are the last cheap checkpoint.

## Inputs

* The imported script: `python -m midnight_archive show --video TMA-0001 --json`
* `python -m midnight_archive review --video TMA-0001 --json` for the automatic
  preflight (0-100) and issue codes.

## Output

Either an edited `Script` JSON re-imported by the owner with
`import-script` (the pipeline currently accepts one script per video), or a
written rejection with the specific reason. Never "improve" a script silently;
every change must be visible in the diff.

## Editing checklist

1. **Cut, don't speed up.** 90-130 words. If it is 140, remove a line.
2. **Spoken English.** Read aloud. Split sentences over 22 words. Replace
   semicolons with full stops.
3. **Hook.** First line <= 8 words and contains the impossible detail.
4. **Continuity.** Names, times, rooms and objects match across beats.
5. **Clues.** Every deduction has an earlier planted detail.
6. **Ending.** Last line <= 12 words, no explanation, no "or was it?".
7. **Originality.** No banned or weak phrases. No premise that duplicates an
   existing idea in the database.
8. **Compliance.** Source recorded for adaptations; speculative science framed
   as fiction; content notes for anything that could be misread as fact.

## Rejection criteria (any one is enough)

* Word count outside 90-130 or estimated duration outside 35-60 s.
* Hook buried after the second sentence.
* A twist that depends on information the viewer never had.
* Logical contradiction: a character ignores an obvious escape or clue.
* A banned phrase, or a premise that duplicates a stored script.
* Anything that reads as a factual claim rather than fiction.

## Commands

```powershell
.\.venv\Scripts\python.exe -m midnight_archive review --video TMA-0001
.\.venv\Scripts\python.exe -m pytest
```

The automatic preflight is not the final QC. It cannot judge voice, edit or
mix; it only measures craft signals. A score below 80 means fix the script, not
the scorer.
