# Give this prompt to your agent

Copy the prompt below into an agent that can read the repository and run Python. Replace the bracketed creative brief. Run production in a fresh workspace created by scripts/create_workspace.py, not in the historical archive checkout.

~~~text
You are helping me make a NEW original cinematic mystery/horror short with The Midnight Archive.

My brief: [theme, premise or "propose three original premises"]
Audience: English-speaking adults.
Target: 45-60 seconds, vertical 1080x1920.
Narration: believable conversational storytelling, restrained emotion, no theatrical horror bass.
Default narrator: Kokoro bm_george, British English, speed 0.96. Do not change a human-approved voice or recording without permission.

Read README.md, AGENTS.md, docs/PRODUCTION_GUIDE.md, config/brand.yaml, config/settings.yaml, agents/story_architect.md, agents/script_editor.md, agents/storyboard.md, and the Script/Storyboard schemas before writing.

1. Check that this is a clean story workspace. If it is the archive checkout, create a new sibling workspace with scripts/create_workspace.py. Do not overwrite or rework the archived TMA-0001 project.
2. Develop my brief. If I have not chosen a premise, propose three specific original concepts with different causes and endings, then wait for my choice.
3. Register the chosen concept with the CLI new command using --select. Read the returned video ID and use it consistently; never assume the next ID.
4. Write a versioned script draft of 90-130 words, preferably natural complete spoken sentences. Open on the impossible detail. Establish the rule and causal chain. Plant the clue needed for the reveal. End with a short line that changes the meaning of the opening. Use short punchy lines only where they earn their emphasis.
5. Use the exact Script schema. Keep narration beats consecutive from 1. Each text field contains only spoken words; keep directions elsewhere. final_line must exactly equal the last beat text. Source must be original, or a verified public-domain adaptation with its reference recorded. Do not put estimated word counts or unsupported fields into the schema.
6. Validate the JSON, import it with import-script, and run review. Report errors and meaningful warnings; fix the draft rather than weakening validators. Preserve every previous version.
7. Create an 8-12 scene storyboard, preferably ten scenes for this format, with contiguous timings and every script word assigned exactly once. Explicitly track locations, time, character appearances, prop details, lighting and reveal order. Provide full 9:16 image prompts and restrained camera/SFX directions. Match the Storyboard schema, validate it and import it.
8. Present the script, estimated runtime, storyboard and any unresolved continuity questions for human creative review. Stop before full production unless I authorize it.
9. After the creative handoff is final, create a separate 15-20-second voice sample with both conversational exposition and a dramatic reveal. Use the approved voice, ordinary natural pacing and restrained pauses. Preserve the exact displayed wording; record any speech-only pronunciation mapping. Keep all raw outputs, settings, model/version/hash data and loudness-matched listening copies. Ask for human listening review.
10. After I approve narration, preserve the approved WAV unchanged. Do not call narrate or produce again if that would regenerate it. Fresh alignment must use the actual approved audio. Make scene timings match that audio; export SRT and ASS and verify exact text coverage.
11. Before any full render, confirm I have authorized one. Keep models, generated assets and their licences/provenance recorded. The ordinary assets command creates Pillow placeholders; it does not automatically reproduce the AI-generated example. Use an explicit versioned image manifest for custom visuals.
12. For an authorized preview, keep narrator identity consistent, protect intelligibility, use restrained music/SFX, preserve earlier artifacts, render one 1080x1920 MP4 and run qc-check. Report technical checks separately from creative judgments.
13. Never award creative approval from a technical pass. Never call approve or publish without explicit human instructions. Publishing is manual.

Coordinate roles sequentially if multiple tools or agents are involved: creative work owns script/storyboard; technical work owns TTS, alignment, mix, rendering and tests. Avoid concurrent edits to shared modules.
~~~

## What to hand back at each gate

| Gate | Required handoff |
|---|---|
| Concept choice | Three alternatives or one user-selected premise, specific ending and causal mechanism |
| Creative review | Script JSON, readable narration, word count/runtime estimate, storyboard JSON, continuity issues |
| Voice review | Sample audio, matching transcript, model/voice/speed/licence, loudness, pronunciation notes |
| Preview review | MP4, approved audio hash, updated scene timings, fresh word alignment/SRT/ASS, technical QC and creative issues |

Do not infer approval from silence or from a numerical score. A test preview is not a release.
