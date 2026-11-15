# Isolated voice lab

This experiment never invokes the production Pipeline, Database, asset registry,
renderer, approval or publication commands. Production defaults are untouched.
Runs have unique versioned directories, raw WAV, loudness-matched WAV, passage,
model hashes/revision, package versions, seed, timing, GPU memory and JSON metadata.
Failed attempts remain available for diagnosis.

## Environment and replay

Run from the project root. Production Python is used for Kokoro, Piper and tests.
Chatterbox uses Python 3.11 in work/voice-lab/env; it needs a separate environment
because its NumPy constraints conflict with production NumPy >=2.0.

    rtk proxy uv venv --python 3.11 work/voice-lab/env
    rtk proxy uv pip install --python work/voice-lab/env/Scripts/python.exe -r experiments/requirements-chatterbox-lock.txt --extra-index-url https://download.pytorch.org/whl/cu124 --index-strategy unsafe-best-match
    rtk proxy .\.venv\Scripts\python.exe experiments/voice_lab.py --backend piper
    rtk proxy .\work\voice-lab\env\Scripts\python.exe experiments/voice_lab.py --backend turbo
    rtk proxy .\work\voice-lab\env\Scripts\python.exe experiments/voice_lab.py --backend chatterbox --exaggeration 0.35

Supply --revision with the commit from a prior metadata-v1.json for model replay.
A missing revision is resolved to a commit and recorded. Cached models are kept
under work/voice-lab/hf-cache. Model loading may also fetch upstream auxiliary
models on first use; keep this cache and capture package versions.
Seeded CUDA generation is not guaranteed to be byte-identical across hardware.

After Freebuff finalizes and versions the revised script, save a verbatim excerpt
with at least three sentences (usually 40-55 spoken words) to a UTF-8 text file.
Use the SAME excerpt, checkpoint, built-in voice conditioning and seed for pacing
or expression comparisons. Do not mix narrator identities in the final video.

    rtk proxy .\work\voice-lab\env\Scripts\python.exe experiments/voice_lab.py --backend turbo --text-file PATH_TO_FINAL_EXCERPT.txt --min-seconds 15 --max-seconds 20 --revision COMMIT_FROM_METADATA
    rtk proxy .\work\voice-lab\env\Scripts\python.exe experiments/voice_lab.py --backend chatterbox --text-file PATH_TO_FINAL_EXCERPT.txt --min-seconds 15 --max-seconds 20 --exaggeration 0.35 --temperature 0.8 --revision COMMIT_FROM_METADATA

Turbo does NOT support Original's exaggeration/CFG controls; its delivery follows
its voice conditioning, punctuation and sampling. Original exposes exaggeration.
The runner uses model-distributed conds.pt, without cloning an external person.
A custom actor reference would need its own documented permission and provenance.

## Listening protocol

Listen to matched-v1.wav with fixed playback volume, preferably without seeing
model labels. Comparisons are mono 48 kHz 24-bit PCM, -23 LUFS integrated, with a
-3 dBTP ceiling. The quieter comparison level preserves dynamics without using
compression merely to make one voice louder. A separate first attempt at -16 LUFS
failed both-target matching; it is retained and is not a fair comparison file.
These targets apply only to auditions, not the production mix.

Review conversational flow, consonants, pronunciation, breath and emphasis,
speaker consistency, restrained emotion, and the reveal. Reject metallic tails,
dropped/repeated words, excess silence or theatrical bass. Note timecodes.
No pitch shifting, time stretching, horror EQ, music or effects are used.
A human listening decision is mandatory; passing machine checks is not a voice
quality judgment. An out-of-range run is marked needs_review, not silently sped up.

## Verification

    rtk proxy .\.venv\Scripts\python.exe -m pytest

Focused tests cover versioning, refusal to write in production directories,
silent/malformed audio measurement, real two-pass matching, PCM format and refusing
to overwrite a matched WAV. Tests use tmp_path and no network.
The CLI can write only to a newly allocated experimental run directory; do not
point it at production output/data/assets/config/source folders.
