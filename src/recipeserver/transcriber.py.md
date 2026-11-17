# The transcriber (`src/recipeserver/transcriber.py`)

```mermaid
flowchart TD
    browser("<img src='barnacle:globe.svg' width='20' alt=''/><br/>browser /api/transcribe<br/>recording bytes") --> decode("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>decode_audio_to_wav()</u><br/>PyAV → 16 kHz mono WAV")
    decode --> server("<img src='barnacle:terminal.svg' width='20' alt=''/><br/><u>WhisperServer</u><br/>ensure_running()")
    server --> post("<img src='barnacle:globe.svg' width='20' alt=''/><br/>POST /inference<br/>multipart → {\"text\": …}")
    click server href "whisper_server.py.md"
    class decode goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

Local speech-to-text for the dictation button. The browser records a short clip with `MediaRecorder` and posts it to `/api/transcribe`; this module turns that clip into text. It is a thin client of the managed [whisper-server](whisper_server.py.md) process ([fordaj/whisper-native](https://github.com/fordaj/whisper-native)):

1. the recording is decoded here, with PyAV, into a 16 kHz mono signed-16-bit WAV,
2. the WAV is posted as multipart form data to `/inference` on the locally managed server,
3. the `text` field of the JSON response is returned.

Decoding happens here rather than in `whisper-server` because miniaudio (the decoder whisper-server uses for uploads) reads WAV/MP3/FLAC/OGG but not the WebM/MP4 containers the browsers record — handing it the original upload answers HTTP 400. Decoding in this repository also keeps the decoder testable on its own.

## `decode_audio_to_wav(data)`

Decodes the recording held in memory and returns WAV bytes. The clip is opened from an `io.BytesIO`, resampled to `SAMPLE_RATE = 16000` mono 16-bit samples, and written with the stdlib `wave` module. A recording that cannot be read, or that carries no audio track, raises `TranscriptionError` — the `/api/transcribe` endpoint turns that into a 400, because a corrupt clip is the caller's mistake, not a server failure.

## `post_inference(base_url, wav_audio, file_name="recording.wav")`

Builds the multipart body by hand (`file`, `response_format=json`, `temperature=0.0`) and posts it to `<base_url>/inference`. An HTTP error from whisper-server raises `TranscriberUnavailable` with the server's own message (503 at the endpoint); an unreachable server raises the same; a response without a `text` field does too.

## `Transcriber`

- `__init__(model=None, server=None)` — `model` is the ggml model name (`RECIPE_SERVER_WHISPER_MODEL` overrides it, defaulting to `base`; it is validated with `normalize_model_name()`). `server` injects a `WhisperServer`, which is what the tests use.
- `transcribe(audio, suffix=".webm")` — decodes the recording and posts the WAV through the managed server. `suffix` is accepted for compatibility with the browser pipeline; the decoder is content-based. Empty audio raises `ValueError`; an undecodable clip raises `TranscriptionError`; the server being down raises `TranscriberUnavailable`.
- `stop()` — stops the managed server (called on app shutdown and when dictation is disabled in the configuration).

`TranscriberUnavailable` is an alias of `WhisperServerUnavailable`, so one `except` clause covers the whole failure family.

The shared instance works like this: `get_transcriber()` creates it on first use, keeps one instance for the whole process (starting whisper-server is expensive), and holds it in one place. [server.py.md](server.py.md) keeps it in its module-level `transcriber`; `stop_transcriber()` tears it down and is called from [core.py.md](core.py.md) on shutdown and on a configuration save that disables dictation.

The model weights are downloaded from Hugging Face on first use and cached in `<user-data>/recipe-server/models/`; the first dictation therefore needs an internet connection and can take a while. Model size is `RECIPE_SERVER_WHISPER_MODEL` (`tiny`, `base`, `base.en`, `small`, `medium`, …).

## Related pages

- [whisper_server.py.md](whisper_server.py.md) — the process lifecycle this module drives
- [server.py.md](server.py.md) — the `/api/transcribe` endpoint that calls the transcriber
- [index_html_generator.py.md](index_html_generator.py.md) — the dictation button in the search field
- [README.md](README.md) — the package hub
