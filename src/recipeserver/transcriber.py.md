# The transcriber (`src/recipeserver/transcriber.py`)

Local speech-to-text for the dictation button. The browser records a short clip with `MediaRecorder` and posts it to `/api/transcribe`; this module turns that clip into text with a local Whisper model through [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## `Transcriber`

- `__init__(model_size=None)` — the model size defaults to `RECIPE_SERVER_WHISPER_MODEL` (environment variable) and falls back to `DEFAULT_MODEL_SIZE = "base"`. `base` transcribes short search phrases quickly without the lag of the larger models.
- `_load_model()` — imports `faster_whisper` and builds the `WhisperModel` on first use (`device="auto"`, `compute_type="default"`). Both the import and the model load are lazy, so starting the application never pays for them. A missing dependency or an unusable model raises `TranscriberUnavailable`.
- `transcribe(audio, suffix=".webm")` — writes the recording to a temporary file with the given suffix (the suffix tells the decoder which container the audio uses), transcribes it (`beam_size=1`, `vad_filter=True`), and returns the recognized text. The temporary file is always removed. Empty audio raises `ValueError`.

The model is expensive to load, so a lock guards the load and the transcription, and the whole module keeps one shared instance: `get_transcriber()` creates it on first use and returns it afterwards. [server.md](server.md) holds that instance in its module-level `transcriber`.

The model weights are downloaded from Hugging Face the first time a recording is transcribed and cached in the local Hugging Face cache; the first dictation therefore needs an internet connection.

## Related pages

- [server.md](server.md) — the `/api/transcribe` endpoint that calls the transcriber
- [index_html_generator.md](index_html_generator.md) — the dictation button in the search field
- [README.md](README.md) — the package hub
