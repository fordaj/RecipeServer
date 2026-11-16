"""Local speech-to-text for the dictation button.

The browser records a short clip with ``MediaRecorder`` and posts it to
``/api/transcribe``; this module turns that clip into text with a local
Whisper model (through ``faster-whisper``).

Both the import of ``faster-whisper`` and the loading of the model happen
lazily, on the first transcription, so starting the application never pays
for them and a missing model is reported as a clear error instead of a
crash at import time.

The recording is decoded here, with PyAV, instead of by
``faster-whisper.decode_audio``: that helper calls ``av.open()`` with a
keyword argument that PyAV 19 removed, which made every transcription fail
with ``TypeError: open() got an unexpected keyword argument
'metadata_errors'``. Decoding here keeps the app working with the PyAV
version that is installed and makes the decode step testable on its own.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import TYPE_CHECKING

from ._logger import logger

if TYPE_CHECKING:  # pragma: no cover - only for the type checker
    import numpy as np

# Model size used when nothing else is configured. "base" transcribes short
# search phrases quickly without the lag of the larger models.
DEFAULT_MODEL_SIZE = "base"

# Environment variable that overrides the model size ("tiny", "base",
# "small", "medium", ...). Any size the local Whisper build supports works.
MODEL_SIZE_ENV_VAR = "RECIPE_SERVER_WHISPER_MODEL"

# The model runs on the CPU by default: a short dictation phrase takes a
# couple of seconds there, and the CPU backend works on every machine.
# "cuda" (or "cuda:0") uses the GPU, and "auto" picks the GPU when it can be
# initialised and falls back to the CPU when it cannot.
DEFAULT_DEVICE = "cpu"
DEVICE_ENV_VAR = "RECIPE_SERVER_WHISPER_DEVICE"

# Beam width and voice-activity detection trade accuracy for speed; a short
# dictation phrase does not need a wide search.
BEAM_SIZE = 1
USE_VAD = True

# Sample rate the Whisper model expects. The recording is resampled to it.
SAMPLE_RATE = 16000


class TranscriberUnavailable(RuntimeError):
    """Raised when the local Whisper model cannot be loaded."""


class TranscriptionError(RuntimeError):
    """Raised when a recording cannot be decoded into audio."""


def decode_audio(path: Path) -> "np.ndarray":
    """Decode the recording at *path* into mono 16 kHz float32 samples.

    Returns a NumPy array of samples, the format the Whisper model takes.
    Raises :class:`TranscriptionError` when the recording cannot be read.
    """
    try:
        import av
        import numpy as np
    except ImportError as exc:  # pragma: no cover - the dependency is required
        raise TranscriberUnavailable("PyAV is not installed. Run 'uv sync' to install it.") from exc

    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise TranscriptionError("The recording has no audio track")

            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            frames = []
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    frames.append(resampled.to_ndarray())

            # The resampler may hold samples back until it is flushed.
            for resampled in resampler.resample(None):
                frames.append(resampled.to_ndarray())
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Unable to decode the recording: {exc}") from exc

    if not frames:
        raise TranscriptionError("The recording has no audio samples")

    # The frames have different lengths, so they are flattened before they are
    # joined into one array of samples.
    samples = np.concatenate([frame.reshape(-1) for frame in frames]).astype(np.float32) / 32768.0

    if samples.size == 0:
        raise TranscriptionError("The recording has no audio samples")

    return samples


class Transcriber:
    """Transcribe recorded audio into text with a local Whisper model."""

    def __init__(self, model_size: str | None = None, model=None, device: str | None = None):
        self.model_size = (model_size or os.environ.get(MODEL_SIZE_ENV_VAR) or DEFAULT_MODEL_SIZE).strip()
        self.device = (device or os.environ.get(DEVICE_ENV_VAR) or DEFAULT_DEVICE).strip().lower()
        self._model = model
        self._lock = Lock()

    def _load_model(self):
        """Load the Whisper model on first use and return it."""
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriberUnavailable("faster-whisper is not installed. Run 'uv sync' to install it.") from exc

        logger.info(f"Loading the Whisper model '{self.model_size}' on {self.device}")

        try:
            self._model = self._build_model(WhisperModel, self.device)
        except Exception as exc:
            if self.device != "auto":
                raise TranscriberUnavailable(
                    f"Unable to load the Whisper model '{self.model_size}' on {self.device}: {exc}. "
                    f"Set {DEVICE_ENV_VAR}=cpu to run the model on the CPU."
                ) from exc

            # "auto" means "the GPU when it works": a machine with a GPU whose
            # runtime libraries are missing still gets a working transcriber.
            logger.warning(f"The GPU could not be initialised ({exc}); falling back to the CPU")
            try:
                self._model = self._build_model(WhisperModel, "cpu")
            except Exception as cpu_exc:
                raise TranscriberUnavailable(f"Unable to load the Whisper model '{self.model_size}': {cpu_exc}") from cpu_exc

        return self._model

    def _build_model(self, whisper_model, device: str):
        return whisper_model(self.model_size, device=device, compute_type="default")

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
                samples = decode_audio(audio_path)
                segments, _info = model.transcribe(samples, beam_size=BEAM_SIZE, vad_filter=USE_VAD)
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
