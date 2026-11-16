# The transcriber (`src/recipeserver/transcriber.py`)

Local speech-to-text for the dictation button. The browser records a short clip with `MediaRecorder` and posts it to `/api/transcribe`; this module decodes that clip and turns it into text with a local Whisper model through [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## `decode_audio(path)`

Decodes a recording into mono 16 kHz float32 samples — the format the Whisper model takes — and returns them as a NumPy array.

The decoding happens here instead of in `faster-whisper.decode_audio()` because that helper calls `av.open()` with a `metadata_errors` argument that PyAV 19 removed. Every transcription then failed with `TypeError: open() got an unexpected keyword argument 'metadata_errors'`. Decoding here keeps the app working with the PyAV version that is installed, and makes the decode step testable on its own.

The clip is opened with PyAV (`av`), resampled to `SAMPLE_RATE = 16000` as mono 16-bit samples, and scaled to float32 in the range -1 to 1. A recording that cannot be read, or that carries no audio, raises `TranscriptionError`.

## `Transcriber`

- `__init__(model_size=None, model=None, device=None)` — the model size defaults to `RECIPE_SERVER_WHISPER_MODEL` (environment variable) and falls back to `DEFAULT_MODEL_SIZE = "base"`. The device defaults to `RECIPE_SERVER_WHISPER_DEVICE` and falls back to `DEFAULT_DEVICE = "cpu"`: the CPU backend works on every machine, and a short dictation phrase takes a couple of seconds there. `model` takes an already built model, which is what the tests use.
- `_load_model()` — imports `faster_whisper` and builds the `WhisperModel` on first use (`compute_type="default"`). Both the import and the model load are lazy, so starting the application never pays for them. A missing dependency or an unusable model raises `TranscriberUnavailable`.
  - A device that cannot be initialised (a GPU whose runtime libraries are missing, for example) also raises `TranscriberUnavailable`, with a message that names `RECIPE_SERVER_WHISPER_DEVICE=cpu`.
  - The device `auto` means "the GPU when it works": when the GPU cannot be initialised, the model is loaded on the CPU instead.
- `transcribe(audio, suffix=".webm")` — writes the recording to a temporary file with the given suffix (the suffix tells the decoder which container the audio uses), decodes it with `decode_audio()`, and transcribes the samples (`beam_size=1`, `vad_filter=True`). The recognized segments are joined into one line, and the temporary file is always removed. Empty audio raises `ValueError`.

The model is expensive to load, so a lock guards the load and the transcription, and the whole module keeps one shared instance: `get_transcriber()` creates it on first use and returns it afterwards. [server.md](server.md) holds that instance in its module-level `transcriber`.

The model weights are downloaded from Hugging Face the first time a recording is transcribed and cached in the local Hugging Face cache (`HF_HOME`); the first dictation therefore needs an internet connection and can take a while.

## Related pages

- [server.md](server.md) — the `/api/transcribe` endpoint that calls the transcriber
- [index_html_generator.md](index_html_generator.md) — the dictation button in the search field
- [README.md](README.md) — the package hub
