"""Local speech-to-text for the dictation button.

The browser records a short clip with ``MediaRecorder`` and posts it to
``/api/transcribe``; this module turns that clip into text with a local
Whisper model (through ``faster-whisper``).

Both the import of ``faster-whisper`` and the loading of the model happen
lazily, on the first transcription, so starting the application never pays
for them and a missing model is reported as a clear error instead of a
crash at import time.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from ._logger import logger

# Model size used when nothing else is configured. "base" transcribes short
# search phrases quickly without the lag of the larger models.
DEFAULT_MODEL_SIZE = "base"

# Environment variable that overrides the model size ("tiny", "base",
# "small", "medium", ...). Any size the local Whisper build supports works.
MODEL_SIZE_ENV_VAR = "RECIPE_SERVER_WHISPER_MODEL"

# Beam width and voice-activity detection trade accuracy for speed; a short
# dictation phrase does not need a wide search.
BEAM_SIZE = 1
USE_VAD = True


class TranscriberUnavailable(RuntimeError):
    """Raised when the local Whisper model cannot be loaded."""


class Transcriber:
    """Transcribe recorded audio into text with a local Whisper model."""

    def __init__(self, model_size: str | None = None):
        self.model_size = (model_size or os.environ.get(MODEL_SIZE_ENV_VAR) or DEFAULT_MODEL_SIZE).strip()
        self._model = None
        self._lock = Lock()

    def _load_model(self):
        """Load the Whisper model on first use and return it."""
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriberUnavailable("faster-whisper is not installed. Run 'uv sync' to install it.") from exc

        try:
            logger.info(f"Loading the Whisper model '{self.model_size}'")
            self._model = WhisperModel(self.model_size, device="auto", compute_type="default")
        except Exception as exc:
            raise TranscriberUnavailable(f"Unable to load the Whisper model '{self.model_size}': {exc}") from exc

        return self._model

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        """Return the spoken text in *audio*.

        *suffix* is the file suffix the recording is written to; it tells the
        decoder which container the audio uses.
        """
        if not audio:
            raise ValueError("Audio recording is empty")

        with self._lock:
            model = self._load_model()

            with NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
                audio_file.write(audio)
                audio_path = Path(audio_file.name)

            try:
                segments, _info = model.transcribe(str(audio_path), beam_size=BEAM_SIZE, vad_filter=USE_VAD)
                return " ".join(segment.text.strip() for segment in segments if segment.text.strip())
            finally:
                audio_path.unlink(missing_ok=True)


# The shared transcriber: the model is expensive to load, so every request
# reuses the same instance.
_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """Return the shared transcriber, creating it on first use."""
    global _transcriber

    if _transcriber is None:
        _transcriber = Transcriber()

    return _transcriber
