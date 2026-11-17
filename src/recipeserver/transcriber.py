"""Local speech-to-text for the dictation button.

The browser records a short clip with ``MediaRecorder`` and posts it to
``/api/transcribe``; this module turns that clip into text.

The transcription engine is the ``whisper-server`` binary from
fordaj/whisper-native (bundled under ``tools/whisper-native/``), which
RecipeServer manages through :mod:`recipeserver.whisper_server`. This
module is a thin client:

1. The recording is decoded here, with PyAV, into a 16 kHz mono WAV — the
   one format every ``whisper-server`` build decodes from memory without
   extra tooling. (miniaudio cannot read the WebM/MP4 containers the
   browsers record, so letting the server decode the original upload
   answers 400.)
2. The WAV is posted as multipart form data to ``/inference`` on the
   locally managed server, and the ``text`` field of the JSON response is
   returned.

Decoding stays in this repository (and not in a helper library) because
the recordings are produced by this app for this app.
"""

from __future__ import annotations

import io
import json
import wave
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ._logger import logger
from .whisper_server import WhisperServer, WhisperServerUnavailable, normalize_model_name

# The transcription failures the HTTP layer surfaces as 503 (the feature is
# down) versus 400 (the recording is bad). Re-exported so the server can
# catch a single family of errors.
TranscriberUnavailable = WhisperServerUnavailable

# Sample rate the Whisper model expects. The recording is resampled to it.
SAMPLE_RATE = 16000

# Beam width and the HTTP read timeout; a short dictation phrase takes a
# couple of seconds on a CPU.
REQUEST_TIMEOUT_SECONDS = 120.0

# Multipart fields posted to /inference. response_format=json keeps the
# answer to a single {"text": "..."} object.
INFERENCE_PATH = "/inference"
RESPONSE_FORMAT = "json"


class TranscriptionError(RuntimeError):
    """Raised when a recording cannot be decoded into audio."""


def decode_audio_to_wav(data: bytes) -> bytes:
    """Decode a recording into 16 kHz mono signed-16-bit WAV bytes.

    Raises :class:`TranscriptionError` when the recording cannot be read.
    """
    try:
        import av
    except ImportError as exc:  # pragma: no cover - the dependency is required
        raise TranscriberUnavailable("PyAV is not installed. Run 'uv sync' to install it.") from exc

    try:
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.audio:
                raise TranscriptionError("The recording has no audio track")

            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            frames = []
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    frames.append(resampled.to_ndarray().tobytes())

            # The resampler may hold samples back until it is flushed.
            for resampled in resampler.resample(None):
                frames.append(resampled.to_ndarray().tobytes())
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Unable to decode the recording: {exc}") from exc

    pcm = b"".join(frames)
    if not pcm:
        raise TranscriptionError("The recording has no audio samples")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _multipart_body(fields: dict[str, str], file_field: str, file_name: str, file_content: bytes, file_content_type: str) -> tuple[bytes, str]:
    boundary = "----RecipeServerTranscriptionBoundary7MA4YWxkTrZu0gW"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
        f"Content-Type: {file_content_type}\r\n\r\n".encode("utf-8") + file_content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


def post_inference(base_url: str, wav_audio: bytes, file_name: str = "recording.wav") -> str:
    """Post a WAV recording to whisper-server and return the transcribed text."""
    body, boundary = _multipart_body(
        {"response_format": RESPONSE_FORMAT, "temperature": "0.0"},
        "file",
        file_name,
        wav_audio,
        "audio/wav",
    )
    request = Request(
        f"{base_url}{INFERENCE_PATH}",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise TranscriberUnavailable(f"whisper-server refused the recording (HTTP {exc.code}): {detail or exc.reason}") from exc
    except URLError as exc:
        raise TranscriberUnavailable(f"whisper-server is not reachable: {exc.reason}") from exc

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TranscriberUnavailable(f"whisper-server answered with something that is not JSON: {payload[:200]!r}") from exc

    text = result.get("text")
    if not isinstance(text, str):
        raise TranscriberUnavailable(f"whisper-server answered without a 'text' field: {payload[:200]!r}")
    return text.strip()


class Transcriber:
    """Transcribe recorded audio into text with the managed whisper-server."""

    def __init__(self, model: str | None = None, server: WhisperServer | None = None):
        # *model* is the ggml model name ("tiny", "base", ...). It only
        # takes effect when *server* is not supplied.
        self.model = normalize_model_name(model)
        self._server = server
        self._lock = Lock()

    def _get_server(self) -> WhisperServer:
        if self._server is None:
            self._server = WhisperServer(model=self.model)
        return self._server

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        """Return the spoken text in *audio*.

        *suffix* is kept for API compatibility with the browser pipeline;
        decoding is content-based, so it is not used.
        """
        if not audio:
            raise ValueError("Audio recording is empty")

        with self._lock:
            wav_audio = decode_audio_to_wav(audio)
            server = self._get_server().ensure_running()
            return post_inference(server.base_url, wav_audio)

    def stop(self) -> None:
        """Stop the managed whisper-server, if any was started."""
        with self._lock:
            if self._server is not None:
                self._server.stop()


# The shared transcriber: starting whisper-server (and loading the model) is
# expensive, so every request reuses the same instance.
_transcriber: Transcriber | None = None
_transcriber_lock = Lock()


def get_transcriber() -> Transcriber:
    """Return the shared transcriber, creating it on first use."""
    global _transcriber

    with _transcriber_lock:
        if _transcriber is None:
            _transcriber = Transcriber()
    return _transcriber


def stop_transcriber() -> None:
    """Stop the shared transcriber's whisper-server, if it is running."""
    global _transcriber

    with _transcriber_lock:
        transcriber = _transcriber
        _transcriber = None
    if transcriber is not None:
        transcriber.stop()
