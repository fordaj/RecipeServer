"""Tests for the local speech-to-text transcriber.

These tests cover the parts of the dictation feature that run on this
machine: decoding the recording the browser sends into a WAV the Ollama
Qwen3-ASR model understands, and handing that WAV to the configured Ollama
server over its native chat API.

Ollama HTTP interactions are mocked; the standard suite never requires a
running Ollama installation (see test_transcription_live.py for the opt-in
test against a real server and model).
"""

from __future__ import annotations

import base64
import io
import json
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from recipeserver.transcriber import (
    SAMPLE_RATE,
    REQUEST_TIMEOUT_SECONDS,
    Transcriber,
    TranscriberUnavailable,
    TranscriptionError,
    decode_audio_to_wav,
    normalize_keep_alive,
    normalize_transcription_text,
    transcribe_wav,
)

FIXTURES = Path(__file__).parent / "fixtures" / "speech"
WAV_FIXTURE = FIXTURES / "chocolate-cake.wav"
WEBM_FIXTURE = FIXTURES / "chocolate-cake.webm"
MP4_FIXTURE = FIXTURES / "chocolate-cake.mp4"

# The length of the recorded phrase, in seconds.
FIXTURE_SECONDS = 1.66


def _read_wav(wav_bytes: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        return wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()


# ----- Decoding ----- #


def test_decode_audio_to_wav_reads_a_wav_recording():
    wav_bytes = decode_audio_to_wav(WAV_FIXTURE.read_bytes())

    assert wav_bytes[:4] == b"RIFF"
    rate, channels, sampwidth, frames = _read_wav(wav_bytes)
    assert (rate, channels, sampwidth) == (SAMPLE_RATE, 1, 2)
    assert frames == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=100)


def test_decode_audio_to_wav_reads_the_webm_the_browser_records():
    """The browser records Opus in WebM; that is what has to decode."""
    wav_bytes = decode_audio_to_wav(WEBM_FIXTURE.read_bytes())

    rate, channels, sampwidth, frames = _read_wav(wav_bytes)
    assert (rate, channels, sampwidth) == (SAMPLE_RATE, 1, 2)
    assert frames == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=100)


def test_decode_audio_to_wav_reads_the_mp4_safari_records():
    """Safari records AAC in MP4 instead of Opus in WebM."""
    wav_bytes = decode_audio_to_wav(MP4_FIXTURE.read_bytes())

    rate, _channels, _sampwidth, frames = _read_wav(wav_bytes)
    assert rate == SAMPLE_RATE
    # The AAC encoder pads the clip, so the length is approximate.
    assert frames == pytest.approx(FIXTURE_SECONDS * SAMPLE_RATE, abs=1500)


def test_both_recordings_hold_the_same_audio():
    webm_bytes = decode_audio_to_wav(WEBM_FIXTURE.read_bytes())
    wav_bytes = decode_audio_to_wav(WAV_FIXTURE.read_bytes())

    assert _read_wav(webm_bytes)[3] == _read_wav(wav_bytes)[3]


def test_decode_audio_rejects_a_recording_that_is_not_audio():
    with pytest.raises(TranscriptionError):
        decode_audio_to_wav(b"this is not audio at all")


def test_decode_audio_rejects_an_empty_recording():
    with pytest.raises(TranscriptionError):
        decode_audio_to_wav(b"")


def test_decode_audio_rejects_a_recording_without_audio():
    """A file that decodes but carries no audio track is not a recording."""
    video_only = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

    with pytest.raises(TranscriptionError):
        decode_audio_to_wav(video_only)


# ----- Response normalisation ----- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("language English<asr_text>Add two cups of flour.", "Add two cups of flour."),
        ("language English<asr_text> Add two cups of flour. ", "Add two cups of flour."),
        ("language english<asr_text>Add two cups of flour.", "Add two cups of flour."),
        ("language Spanish<asr_text>Añade dos tazas.", "Añade dos tazas."),
        ("languageEnglish<asr_text>Add two cups.", "Add two cups."),
        ("<asr_text>Chocolate cake.", "Chocolate cake."),
        ("Chocolate cake.", "Chocolate cake."),
        ("language English<asr_text>", ""),
        ("language English<asr_text>One two<asr_text>three", "One twothree"),
        ("", ""),
        (None, ""),
        (123, ""),
    ],
)
def test_normalize_transcription_text(raw, expected):
    assert normalize_transcription_text(raw) == expected


def test_normalize_transcription_text_strips_trailing_special_tokens():
    assert normalize_transcription_text("language English<asr_text>Chocolate cake.<|im_end|>") == "Chocolate cake."
    assert normalize_transcription_text("Chocolate cake.<|im_end|>") == "Chocolate cake."


# ----- keep_alive normalisation ----- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("-1", -1),
        ("0", 0),
        ("300", 300),
        ("10m", "10m"),
        ("1h", "1h"),
    ],
)
def test_normalize_keep_alive(raw, expected):
    assert normalize_keep_alive(raw) == expected


# ----- The HTTP client ----- #


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.payload if limit is None or limit < 0 else self.payload[:limit]


def _ollama_payload(text: str, **extra) -> bytes:
    body = {
        "model": "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": "stop",
    }
    body.update(extra)
    return json.dumps(body).encode("utf-8")


def test_transcribe_wav_posts_the_recording_to_the_chat_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["content_type"] = request.headers["Content-type"]
        captured["timeout"] = timeout
        return FakeResponse(_ollama_payload("language English<asr_text>Chocolate cake."))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    text = transcribe_wav("http://localhost:11434", "test-model:q8", b"RIFF-wav-bytes")

    assert text == "Chocolate cake."
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["body"]["model"] == "test-model:q8"
    assert captured["body"]["stream"] is False
    assert captured["body"]["think"] is False
    assert "keep_alive" not in captured["body"]
    message = captured["body"]["messages"][0]
    assert message["role"] == "user"
    assert base64.b64decode(message["images"][0]) == b"RIFF-wav-bytes"


def test_transcribe_wav_normalises_the_configured_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        return FakeResponse(_ollama_payload("hello"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    transcribe_wav("http://localhost:11434/v1", "test-model:q8", b"wav")

    assert captured["url"] == "http://localhost:11434/api/chat"


def test_transcribe_wav_sends_keep_alive_when_configured(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["body"] = json.loads(request.data)
        return FakeResponse(_ollama_payload("hello"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    transcribe_wav("http://localhost:11434", "test-model:q8", b"wav", "10m")
    assert captured["body"]["keep_alive"] == "10m"

    transcribe_wav("http://localhost:11434", "test-model:q8", b"wav", "-1")
    assert captured["body"]["keep_alive"] == -1


def test_transcribe_wav_surfaces_a_missing_model(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(request, timeout=0):
        raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"model \'x\' not found"}'))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "missing-model:latest", b"wav")

    message = str(error.value)
    assert "missing-model:latest" in message
    assert "ollama pull" in message


def test_transcribe_wav_surfaces_other_http_errors(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(request, timeout=0):
        raise HTTPError(request.full_url, 500, "Internal Server Error", {}, io.BytesIO(b"boom"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")

    assert "500" in str(error.value)
    assert "boom" in str(error.value)


def test_transcribe_wav_reports_an_unreachable_server(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(request, timeout=0):
        raise URLError("Connection refused")

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")

    assert "not reachable" in str(error.value)


def test_transcribe_wav_reports_a_timeout(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(request, timeout=0):
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")

    assert "did not answer" in str(error.value)


def test_transcribe_wav_rejects_a_response_that_is_not_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("recipeserver.transcriber.urlopen", lambda request, timeout=0: FakeResponse(b"<html>nope</html>"))

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")

    assert "not JSON" in str(error.value)


def test_transcribe_wav_rejects_an_error_payload(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "recipeserver.transcriber.urlopen",
        lambda request, timeout=0: FakeResponse(json.dumps({"error": "model 'x' not found"}).encode("utf-8")),
    )

    with pytest.raises(TranscriberUnavailable) as error:
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")

    assert "model 'x' not found" in str(error.value)


def test_transcribe_wav_rejects_a_response_without_a_message(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("recipeserver.transcriber.urlopen", lambda request, timeout=0: FakeResponse(b"{}"))

    with pytest.raises(TranscriberUnavailable):
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")


def test_transcribe_wav_rejects_a_message_without_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "recipeserver.transcriber.urlopen",
        lambda request, timeout=0: FakeResponse(json.dumps({"message": {"role": "assistant"}}).encode("utf-8")),
    )

    with pytest.raises(TranscriberUnavailable):
        transcribe_wav("http://localhost:11434", "test-model:q8", b"wav")


def test_transcribe_wav_returns_an_empty_transcription_for_silence(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "recipeserver.transcriber.urlopen",
        lambda request, timeout=0: FakeResponse(_ollama_payload("")),
    )

    assert transcribe_wav("http://localhost:11434", "test-model:q8", b"wav") == ""


# ----- Transcribing ----- #


def test_transcribe_decodes_and_posts_the_recording(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["body"] = json.loads(request.data)
        return FakeResponse(_ollama_payload("language English<asr_text>Chocolate cake."))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    transcriber = Transcriber()
    text = transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm", endpoint="http://localhost:11434", model="test-model:q8")

    assert text == "Chocolate cake."
    audio = base64.b64decode(captured["body"]["messages"][0]["images"][0])
    assert audio[:4] == b"RIFF"
    rate, channels, _sampwidth, _frames = _read_wav(audio)
    assert (rate, channels) == (SAMPLE_RATE, 1)


def test_transcribe_rejects_an_empty_recording():
    transcriber = Transcriber()

    with pytest.raises(ValueError):
        transcriber.transcribe(b"", suffix=".webm", endpoint="http://localhost:11434", model="test-model:q8")


def test_transcribe_reports_a_recording_it_cannot_decode():
    transcriber = Transcriber()

    with pytest.raises(TranscriptionError):
        transcriber.transcribe(b"not audio", suffix=".webm", endpoint="http://localhost:11434", model="test-model:q8")
