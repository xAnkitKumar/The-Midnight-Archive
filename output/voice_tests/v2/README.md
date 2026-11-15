# TMA-0001 narration audition — v2

**Status: awaiting human review. No full narration, render, QC pass or approval has been produced.**

## Selected voice

| Item | Value |
|---|---|
| Model | Kokoro-82M (`kokoro-v1.0.onnx`) |
| Voice | `am_michael` (US English male) |
| Runtime | `kokoro-onnx 0.6.1` on CPU |
| Sample rate | 24 kHz mono |
| Model/voice licence | Apache-2.0 (as declared by the Kokoro-82M model repository) |
| Runtime licence | MIT (`kokoro-onnx`) |
| Commercial use | Permitted by the declared model/runtime licences; retain the attribution below |

Attribution: “Kokoro-82M (Apache-2.0) by hexgrad; voice `am_michael`; ONNX runtime `kokoro-onnx` (MIT).”

Kokoro was chosen over Piper and Chatterbox for this passage because it gives a warm,
grounded male conversational read without the announce-y cadence of the old Piper
voice. Chatterbox is more expressive but heavier and its repository is retired;
Piper remains a fast fallback, not the casting choice.

## Audition passage

> Elias's paper had his obituary. It arrived a day early: his apartment, a fire at
> 3:07. He was alive. The next paper said Mara Kwan. She'd entered 4B to warn him.
> The paper wasn't predicting the future. It was choosing who paid for it.

44 words. It contains conversational exposition (the paper, the ordinary details of
the apartment and time) and the dramatic revelation (Mara entered 4B to warn him,
then the reframing line).

## Files

Use the **level-matched** folder for A/B comparison. The peak-normalized files in the
parent folder are the raw mastered masters.

| Candidate | File | Duration | Pacing |
|---|---|---|---|
| **A — recommended** | `level-matched/kokoro-am_michael-a-natural.wav` | 19.896 s | one continuous pass, speed 0.96; punctuation carries the pauses |
| **B — alternate** | `level-matched/kokoro-am_michael-b-directed.wav` | 19.947 s | exposition at 0.98, 300 ms bridge, final two sentences at 0.93 |
| C — British reference | `level-matched/kokoro-bm_george-reference.wav` | 18.293 s | one pass, speed 0.96 |
| D — old baseline | `level-matched/piper-en_US-ljspeech-high-baseline.wav` | 15.496 s | Piper `en_US-ljspeech-high`, female, length scale 1.0 |

A is the recommendation because it is a single performance with no constructed
pause and the least “directed” feel. B is the controlled pacing experiment: it
slows only the final line and adds one 300 ms bridge. It is included so the owner
can decide whether that weight helps or feels imposed.

Peak-normalized masters are at the parent paths without `level-matched/`.
All comparison copies are matched to −22.41 dBFS RMS so the louder voice does not
win by volume alone. The peak-normalized masters are all at −1.5 dBFS peak.

## Machine checks

- Duration: all four candidates are inside the requested 15–20 s window.
- Peak: −1.5 dBFS on each peak-normalized master.
- Pauses: no added dramatic silence. A has a longest low-energy gap of 0.70 s;
  B has 0.76 s including the 300 ms bridge. These are natural sentence gaps, not
  trailer-style beats.
- ASR: faster-whisper `base.en`, not a listening test.
  - Raw WER: A 15.9%, B 13.6%, C 6.8%, D 11.4%.
  - After normalising the recurring proper-noun/numeral variants (`Mara quam`,
    `Lara quam`, `Eliza`, `full B`, `three zero seven`): A 9.1%, B 2.3%,
    C 2.3%, D 2.3%.
  - The errors are concentrated in “Mara Kwan” and, for Piper, “Elias”. A human
    must judge whether the names are clear enough; changing spelling or adding a
    pronunciation override would be a separate script/TTS decision.

Raw measurements and transcripts: `measurements.json`, `level-matched/measurements.json`,
`asr.json`.

## Licensing notes

- Kokoro-82M weights and voice pack: Apache-2.0.
- `kokoro-onnx`: MIT.
- Piper engine: GPL-3.0. The Piper baseline voice `en_US-ljspeech-high` is trained on
  the public-domain LJSpeech dataset.
- No paid API, voice clone or external reference recording was used.
- This is a licence review, not legal advice. Keep the attribution in the final
  credits/metadata and re-check the upstream model card before commercial release.

## Decision requested

Pick **A**, **B**, or **C** (or request another pass). Do not approve the video or
start the full render until this sample has been reviewed by a human.
