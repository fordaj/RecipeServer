"""Tests for the local speech-to-text transcriber.

These tests cover the parts of the dictation feature that run on this
machine: decoding the recording the browser sends, handing the decoded
samples to the Whisper model, and the rules that decide which model and
which device are used.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from recipeserver.transcriber import (
    DEFAULT_DEVICE,
    DEVICE_ENV_VAR,
    SAMPLE_RATE,
    Transcriber,
    TranscriberUnavailable,
    TranscriptionError,
    decode_audio,
)

FIXTURES = Path(__file__).parent / "fixtures" / "speech"
WAV_FIXTURE = FIXTURES / "chocolate-cake.wav"
WEBM_FIXTURE = FIXTURES / "chocolate-cake.webm"
MP4_FIXTURE = FIXTURES / "chocolate-cake.mp4"

# The length of the recorded phrase, in seconds.
FIXTURE_SECONDS = 1.66


class FakeSegment:
    def __init__(self, text: str):
        self.text = text


class FakeModel:
    """Stand-in for the Whisper model."""

    def __init__(self, segments=("chocolate cake",)):
        self.segments = list(segments)
        self.calls: list[dict] = []
        self.samples = None

    def transcribe(self, samples, **kwargs):
        self.calls.append(kwargs)
        self.samples = samples
        return [FakeSegment(text) for text in self.segments], None


@pytest.fixture()
def fake_faster_whisper(monkeypatch: pytest.MonkeyPatch):
    """Install a stand-in for the faster-whisper package.

    The factory records the arguments it is called with, so the tests can
    assert which model and device are used.
    """
    module = types.ModuleType("faster_whisper")
    module.calls = []

    def whisper_model(model_size, device="auto", compute_type="default"):
        module.calls.append({"model_size": model_size, "device": device, "compute_type": compute_type})
        return FakeModel()

    module.WhisperModel = whisper_model
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return module


# ----- Decoding ----- #


def test_decode_audio_reads_a_wav_recording():
    samples = decode_audio(WAV_FIXTURE)

    assert isinstance(samples, np.ndarray)
    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert samples.size == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=100)
    # The samples are normalized audio, not raw 16-bit values.
    assert samples.min() >= -1.0
    assert samples.max() <= 1.0


def test_decode_audio_reads_the_webm_the_browser_records():
    """The browser records Opus in WebM; that is what has to decode."""
    samples = decode_audio(WEBM_FIXTURE)

    assert samples.dtype == np.float32
    assert samples.size == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=100)


def test_both_recordings_hold_the_same_audio():
    assert decode_audio(WEBM_FIXTURE).size == decode_audio(WAV_FIXTURE).size


def test_decode_audio_reads_the_mp4_safari_records():
    """Safari records AAC in MP4 instead of Opus in WebM."""
    samples = decode_audio(MP4_FIXTURE)

    assert samples.dtype == np.float32
    # The AAC encoder pads the clip, so the length is approximate.
    assert samples.size == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=1500)


def test_decode_audio_rejects_a_recording_that_is_not_audio(tmp_path: Path):
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"this is not audio at all")

    with pytest.raises(TranscriptionError):
        decode_audio(broken)


def test_decode_audio_rejects_an_empty_recording(tmp_path: Path):
    empty = tmp_path / "empty.webm"
    empty.write_bytes(b"")

    with pytest.raises(TranscriptionError):
        decode_audio(empty)


def test_decode_audio_rejects_a_recording_without_audio(tmp_path: Path):
    """A file that decodes but carries no audio track is not a recording."""
    video_only = tmp_path / "video.mp4"
    video_only.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)

    with pytest.raises(TranscriptionError):
        decode_audio(video_only)


# ----- Transcribing ----- #


def test_transcribe_hands_the_model_the_decoded_samples():
    model = FakeModel()
    transcriber = Transcriber(model=model)

    text = transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert text == "chocolate cake"
    # The model gets the samples, not a file name: faster-whisper decodes
    # files with a PyAV call that no longer works with PyAV 19.
    assert isinstance(model.samples, np.ndarray)
    assert model.samples.dtype == np.float32
    assert model.samples.size == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=100)


def test_transcribe_joins_the_segments():
    model = FakeModel(segments=("chocolate", "cake", "please"))
    transcriber = Transcriber(model=model)

    assert transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm") == "chocolate cake please"


def test_transcribe_skips_empty_segments():
    model = FakeModel(segments=("chocolate", "", "  ", "cake"))
    transcriber = Transcriber(model=model)

    assert transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm") == "chocolate cake"


def test_transcribe_rejects_an_empty_recording():
    transcriber = Transcriber(model=FakeModel())

    with pytest.raises(ValueError):
        transcriber.transcribe(b"", suffix=".webm")


def test_transcribe_reports_a_recording_it_cannot_decode():
    transcriber = Transcriber(model=FakeModel())

    with pytest.raises(TranscriptionError):
        transcriber.transcribe(b"not audio", suffix=".webm")


def test_the_model_is_loaded_once(fake_faster_whisper):
    transcriber = Transcriber(model_size="tiny")

    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")
    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert len(fake_faster_whisper.calls) == 1


# ----- Model and device ----- #


def test_the_model_runs_on_the_cpu_by_default(fake_faster_whisper):
    transcriber = Transcriber(model_size="tiny")

    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert fake_faster_whisper.calls[0]["device"] == DEFAULT_DEVICE == "cpu"


def test_the_device_can_be_configured(fake_faster_whisper, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(DEVICE_ENV_VAR, "cuda")

    transcriber = Transcriber(model_size="tiny")
    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert fake_faster_whisper.calls[0]["device"] == "cuda"


def test_a_broken_device_reports_how_to_run_on_the_cpu(monkeypatch: pytest.MonkeyPatch):
    """A GPU whose runtime libraries are missing must not fail the request."""
    module = types.ModuleType("faster_whisper")

    def whisper_model(model_size, device="auto", compute_type="default"):
        raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")

    module.WhisperModel = whisper_model
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    transcriber = Transcriber(model_size="tiny")

    with pytest.raises(TranscriberUnavailable) as error:
        transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert DEVICE_ENV_VAR in str(error.value)
    assert "cpu" in str(error.value)


def test_auto_falls_back_to_the_cpu_when_the_gpu_is_unusable(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("faster_whisper")
    module.calls = []

    def whisper_model(model_size, device="auto", compute_type="default"):
        module.calls.append(device)
        if device != "cpu":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return FakeModel()

    module.WhisperModel = whisper_model
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    transcriber = Transcriber(model_size="tiny", device="auto")
    text = transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert text == "chocolate cake"
    assert module.calls == ["auto", "cpu"]


def test_a_missing_faster_whisper_is_reported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)

    transcriber = Transcriber(model_size="tiny")

    with pytest.raises(TranscriberUnavailable):
        transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")
