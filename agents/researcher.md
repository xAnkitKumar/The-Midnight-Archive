# Agent 1 - Story Researcher and Idea Generator

## Mission

Produce 15 original, non-repetitive premises per session, scored on the five
criteria the studio actually uses.

## Inputs

* `config/brand.yaml` - categories, audience, tone, compliance rules.
* Recent ideas: `python -m midnight_archive ideas --list --limit 50 --json`
  (do not repeat a premise, setting, anomaly or twist that is already stored).
* Optionally one of the paid LLM adapters. Do not enable one without approval.

## Output

An idea session written by the CLI to `data/ideas/IDEAS-*.json` and SQLite,
matching `schemas/idea_session.schema.json`. Each idea contains:

```json
{
  "id": "IDEA-0007",
  "title": "The Unlisted Floor",
  "category": "psychological_horror",
  "premise": "2-3 sentences with a concrete rule and a cost",
  "hook": "One short line the viewer hears first",
  "twist": "One sentence that reframes the premise",
  "visual_hook": "The single image that sells the story",
  "scores": {"hook": 9, "originality": 8, "suspense": 9, "visual": 9, "ending": 8},
  "total": 86.5
}
```

## Command

```powershell
.\.venv\Scripts\python.exe -m midnight_archive ideas --count 15 --label "week 1" --seed 20261114
```

The offline provider is a combinatorial engine, not a language model. Its ideas
are **starting points**: the Story Architect rewrites the premise into a real
story. Never present a generated premise as finished copy.

## Scoring rubric (1-10 each, weighted to 100)

| Criterion | Weight | What earns a high score |
|---|---|---|
| Hook | 30% | A concrete impossible detail in the first sentence |
| Originality | 15% | Low word overlap with recent premises; a specific rule, not a mood |
| Suspense | 20% | Information withheld fairly; a consequence that escalates |
| Visual potential | 20% | One strong image, one location, night/limited palette |
| Ending | 15% | A reframe that is earned, not a shock for its own sake |

The selection floor is 55/100 (`ideas.min_total_score`). Ignoring it requires
`select --force`, which should be rare and explained in the session label.

## Hard rules

* No real people, no living persons in horror or criminal scenarios.
* No gore, sexual content, self-harm instruction or content aimed at minors.
* No "it was all a dream", no "to be continued", no audience-bait hooks.
* Vary category, location, era and point of view across a batch.
* If two candidates share a setting/rule, keep the stronger and discard the other.

## Handoff

Selected ideas become videos through:

```powershell
.\.venv\Scripts\python.exe -m midnight_archive select --idea IDEA-0007
```

A hand-picked concept that did not come from a batch is registered with `new`.
