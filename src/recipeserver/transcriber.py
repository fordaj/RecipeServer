from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from faster_whisper import WhisperModel


class Transcriber:
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._model: WhisperModel | None = None
        self._lock = Lock()

    def _load_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device="auto",
                compute_type="default",
            )

        return self._model

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        if not audio:
            raise ValueError("Audio recording is empty")

        with self._lock:
            model = self._load_model()

            with NamedTemporaryFile(
                suffix=suffix,
                delete=False,
            ) as audio_file:
                audio_file.write(audio)
                audio_path = Path(audio_file.name)

            try:
                segments, _ = model.transcribe(
                    str(audio_path),
                    beam_size=1,
                    vad_filter=True,
                )

                return " ".join(segment.text.strip() for segment in segments if segment.text.strip())

            finally:
                audio_path.unlink(missing_ok=True)
