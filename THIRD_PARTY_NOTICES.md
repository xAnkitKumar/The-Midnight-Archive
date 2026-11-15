# Third-party notices and provenance

The project does not assign a single licence to all files. Original code/story/media ownership is separate from the components below. No blanket open-source licence has been selected for the original project.

| Component | Recorded licence | Source / retained notice |
|---|---|---|
| Kokoro-82M model and voice pack | Apache-2.0 | https://huggingface.co/hexgrad/Kokoro-82M ; licenses/kokoro-model-card.md ; licenses/Apache-2.0.txt |
| ONNX distribution | Kokoro model under Apache-2.0 | https://github.com/thewh1teagle/kokoro-onnx ; model and voice files retained byte-for-byte |
| kokoro-onnx runtime | MIT | https://github.com/thewh1teagle/kokoro-onnx ; licenses/kokoro-onnx-MIT.txt ; installed separately by pip |
| Piper runtime | GPL-3.0 | https://github.com/OHF-Voice/piper1-gpl ; installed separately, not bundled as a binary/venv |
| Piper LJSpeech high voice | Upstream model card identifies its dataset as public domain | https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ljspeech/high ; licenses/piper-ljspeech-MODEL_CARD.txt |
| Montserrat Bold | SIL OFL 1.1 | assets/fonts/Montserrat-OFL.txt ; https://github.com/JulietaUla/Montserrat |
| faster-whisper / Whisper | MIT code/model records | https://github.com/SYSTRAN/faster-whisper ; https://github.com/openai/whisper ; installed/downloaded separately |
| FFmpeg | Build-dependent LGPL/GPL terms | https://ffmpeg.org/legal.html ; installed separately, not bundled |
| Generated artwork | Applicable generation-service terms, not a stock/software licence | Per-artifact provenance in output/drafts/TMA-0001/test-render-v1/provenance/ |
| Procedural music/SFX and Pillow stills | Original production material | Source and hashes in asset manifests |

The upstream Piper card labels the **dataset** licence; do not treat that as a universal licence for the Piper engine. The original manifest's Public Domain designation is retained as historical provenance.

The model weights in assets/ are unmodified copies. Dependencies are installed from requirements.txt; virtual environments, FFmpeg binaries, GPU libraries and Chatterbox model caches are not redistributed here.

The historical source/licence assessments under archive/work/voice-lab/ are dated research notes. They do not make F5-TTS pretrained weights commercially usable, and they do not authorize cloning an external actor's voice.

Exact downloaded notice URLs are in licenses/sources.json. Preserve these notices and all per-artifact provenance when sharing this repository.
