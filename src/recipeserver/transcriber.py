"""Speech-to-text for the dictation button.

The browser records a short clip with ``MediaRecorder`` and posts it to
``/api/transcribe``; this module turns that clip into text.

The transcription engine is an Ollama server running the Qwen3-ASR model,
managed entirely outside of RecipeServer: RecipeServer only sends audio and
reads back the transcription. It never downloads, installs, launches, or
otherwise manages Ollama or its models. The browser posts the recording
here; this module:

1. Decodes the recording with PyAV into a 16 kHz mono WAV — the audio
   encoders every browser ships differ, and the model wants plain PCM.
2. Base64-embeds the WAV in a ``POST /api/chat`` request to the configured
   Ollama server (the same native chat route the other local AI features
   use), with the audio carried in the message's ``images`` list — the
   Ollama transport for the Qwen3-ASR audio encoder. The request is not
   streamed and disables hidden thinking, like every other Ollama chat
   request RecipeServer sends.
3. Normalises the model's reply: the Qwen3-ASR family answers with a
   ``language <name><asr_text><transcription>`` envelope, which is stripped
   before the text is returned to the caller.

Decoding stays in this repository (and not in a helper library) because the
recordings are produced by this app for this app.
"""

from __future__ import annotations

import base64
import io
import json
import re
import wave
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ._logger import logger
from .ai_recipe import normalize_ollama_base_url


# The transcription failures the HTTP layer surfaces as 503 (the feature is
# down) versus 400 (the recording is bad). The server catches this family as
# a single "transcription unavailable" condition.
class TranscriberUnavailable(RuntimeError):
    """Raised when the transcription server or model cannot be used."""


# Sample rate the model expects. The recording is resampled to it.
SAMPLE_RATE = 16000

# The first request to a cold Ollama server loads the model into memory,
# which can take a while on a modest GPU/CPU; inference itself is quick.
# Generous, because a dictation that fails with "timed out" while the model
# was still loading is the bug reports this avoids.
REQUEST_TIMEOUT_SECONDS = 180.0

# How much of an error response body to quote in the raised message.
ERROR_BODY_READ_BYTES = 2048

# Hard ceiling on the JSON body Ollama returns; a transcription reply is a
# few hundred bytes.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024

OLLAMA_CHAT_PATH = "/api/chat"

# The Qwen3-ASR models answer with a ``language <name><asr_text>`` envelope
# around the transcription. Some builds omit the language tag and emit only
# the marker.
_LANGUAGE_MARKER_PATTERN = re.compile(r"(?is)^\s*language\s*:?\s*[^<\n]*<asr_text>")
_BARE_MARKER_PATTERN = re.compile(r"(?is)<asr_text>")
# Defensive: never leak special tokens into the field the user sees.
_TRAILING_SPECIAL_TOKENS_PATTERN = re.compile(r"(?:<\|im_end\|>|<\|endoftext\|>|<\|im_start\|>)+\s*$")


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


def normalize_transcription_text(raw: object) -> str:
    """Strip the Qwen3-ASR envelope from a model reply.

    Returns the transcription text, or an empty string when the model said
    nothing recognisable. Unknown shapes are returned verbatim (stripped of
    surrounding whitespace), so text from a model without the marker is not
    mangled.
    """
    if not isinstance(raw, str):
        return ""

    text = raw.strip()
    text = _LANGUAGE_MARKER_PATTERN.sub("", text, count=1)
    text = _BARE_MARKER_PATTERN.sub("", text)
    text = _TRAILING_SPECIAL_TOKENS_PATTERN.sub("", text)
    return text.strip()


def _build_chat_payload(model: str, wav_audio: bytes, keep_alive: object = None) -> dict:
    """Build the native ``/api/chat`` request body for one transcription."""
    payload = {
        "model": model,
        # The Qwen3-ASR GGUF accepts the audio in the message's images list.
        "messages": [
            {
                "role": "user",
                "content": "",
                "images": [base64.b64encode(wav_audio).decode("ascii")],
            }
        ],
        "stream": False,
        # Disables hidden reasoning on thinking-capable models; accepted and
        # ignored elsewhere.
        "think": False,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    return payload


def normalize_keep_alive(value: object) -> object | None:
    """Normalise the configured keep-alive for the request body.

    Returns ``None`` when unset (Ollama applies its own default). Values that
    are plain integers become JSON numbers (seconds; Ollama treats a negative
    value as "keep loaded indefinitely" and ``0`` as "unload now"); anything
    else is passed through verbatim (a Go duration string such as ``"5m"``).
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text, 10)
    except ValueError:
        return text


def transcribe_wav(endpoint: str, model: str, wav_audio: bytes, keep_alive: object = None) -> str:
    """Post a WAV recording to the Ollama chat API and return the text."""
    base_url = normalize_ollama_base_url(endpoint)
    chat_url = f"{base_url}{OLLAMA_CHAT_PATH}"
    body = json.dumps(_build_chat_payload(model, wav_audio, normalize_keep_alive(keep_alive))).encode("utf-8")
    request = Request(
        chat_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    logger.info(f"Requesting transcription from {chat_url} (model={model}, audio_bytes={len(wav_audio)})")

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        detail = exc.read(ERROR_BODY_READ_BYTES).decode("utf-8", errors="replace").strip()
        if exc.code == 404:
            raise TranscriberUnavailable(
                f"The model {model!r} is not installed on the Ollama server at {base_url}. Pull it first: ollama pull {model}"
            ) from exc
        raise TranscriberUnavailable(f"The transcription server refused the request (HTTP {exc.code}) at {base_url}: {detail or exc.reason}") from exc
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError) or _is_timeout(reason):
            raise TranscriberUnavailable(
                f"The Ollama server at {base_url} did not answer within {REQUEST_TIMEOUT_SECONDS:.0f} seconds. "
                "The model may still be loading; try again."
            ) from exc
        raise TranscriberUnavailable(f"The Ollama server at {base_url} is not reachable: {reason}") from exc
    except TimeoutError as exc:
        raise TranscriberUnavailable(
            f"The Ollama server at {base_url} did not answer within {REQUEST_TIMEOUT_SECONDS:.0f} seconds. The model may still be loading; try again."
        ) from exc

    if len(payload) > MAX_RESPONSE_BYTES:
        raise TranscriberUnavailable("The transcription server returned an oversized response")

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TranscriberUnavailable(f"The transcription server answered with something that is not JSON: {payload[:200]!r}") from exc

    return _extract_transcription(result, model=model)


def _is_timeout(reason: object) -> bool:
    text = str(reason).lower()
    return "timed out" in text or "timeout" in text


def _extract_transcription(payload: object, *, model: str) -> str:
    """Validate the chat response and return the normalised transcription.

    A well-formed reply whose transcription is empty (silence) yields an
    empty string; a malformed one raises :class:`TranscriberUnavailable`.
    """
    if not isinstance(payload, dict):
        raise TranscriberUnavailable(f"The transcription server returned an invalid response: {str(payload)[:200]!r}")

    error = payload.get("error")
    if error:
        raise TranscriberUnavailable(f"The transcription server returned an error: {error}")

    message = payload.get("message")
    if not isinstance(message, dict):
        raise TranscriberUnavailable(f"The transcription server returned a response without a message: {str(payload)[:200]!r}")

    content = message.get("content")
    if not isinstance(content, str):
        raise TranscriberUnavailable(f"The transcription server returned a message without text content: {str(payload)[:200]!r}")

    text = normalize_transcription_text(content)
    logger.info(f"Transcription from {model}: {len(text)} characters")
    logger.debug(f"Transcription preview: {text[:200]!r}")
    return text


class Transcriber:
    """Transcribe recorded audio with the configured Ollama Qwen3-ASR model.

    The instance carries no state: every call reads the endpoint, model and
    keep-alive handed to :meth:`transcribe`, so configuration changes take
    effect without restarting anything.
    """

    def transcribe(self, audio: bytes, suffix: str = ".webm", *, endpoint: str, model: str, keep_alive: object = None) -> str:
        """Return the spoken text in *audio*.

        *suffix* is kept for API compatibility with the browser pipeline;
        decoding is content-based, so it is not used.
        """
        if not audio:
            raise ValueError("Audio recording is empty")

        wav_audio = decode_audio_to_wav(audio)
        return transcribe_wav(endpoint, model, wav_audio, keep_alive)


# The shared transcriber. It is stateless; keeping one instance mirrors the
# other request-scoped helpers and keeps the server module easy to fake in
# tests.
transcriber = Transcriber()


def get_transcriber() -> Transcriber:
    """Return the shared (stateless) transcriber."""
    return transcriber
