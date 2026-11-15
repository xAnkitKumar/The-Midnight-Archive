# Agent 5 - Visual Asset Producer (Phase 2, not yet implemented)

> **Status:** contract only. There is no image-generation code in Phase 1 and
> `assets/` is empty. Do not fabricate assets, and do not wire a paid provider
> without the owner's explicit approval.

## Mission

Turn storyboard image prompts into a consistent set of 1080x1920 stills, with
the provenance of every file recorded.

## Planned inputs

* `Storyboard` from a `STORYBOARD_READY` video.
* Character sheets in `assets/characters/` (one reference per named character).
* Style bible from the storyboard and `config/brand.yaml`.

## Planned output

* One image per scene in `output/drafts/<video-id>/images/`.
* A row in `assets` (SQLite) and `assets/MANIFEST.md` for every file:
  provider, model or source URL, licence, attribution, generation date, seed.
* Video moves to `ASSETS_READY` only when every scene has a validated image.

## Consistency rules

1. Generate the character reference first, then reuse it in every prompt.
2. Keep one location reference per environment, one palette per story.
3. Never mix providers mid-story; grain and colour drift.
4. All prompts are 9:16, cinematic, no text, no watermark.
5. Reject any frame with deformed hands, duplicate faces, modern UI or
   unreadable lettering that the edit cannot hide.

## Licences

* Only models and asset packs that permit commercial use.
* Record the licence name and a source URL for every third-party asset.
* Never use a random Pinterest/Google image, a film still or a living artist's
  distinctive style.
* Stock footage is a last resort and must be licensed, logged and visually
  graded to match the story.

## Cost gate

No paid image API calls without a written approval in the session notes and an
explicit budget. Free local options are preferred; the adapters will live in
`midnight_archive/asset_manager.py` behind a provider interface.
