"""Tests for the local speech-to-text transcriber.

These tests cover the parts of the dictation feature that run on this
machine: decoding the recording the browser sends into a WAV the
whisper-server understands, and handing that WAV to the managed server.

The lifecycle of the whisper-server process itself is covered in
test_whisper_server.py.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest

from recipeserver.transcriber import (
    SAMPLE_RATE,
    Transcriber,
    TranscriberUnavailable,
    TranscriptionError,
    decode_audio_to_wav,
    post_inference,
)

FIXTURES = Path(__file__).parent / "fixtures" / "speech"
WAV_FIXTURE = FIXTURES / "chocolate-cake.wav"
WEBM_FIXTURE = FIXTURES / "chocolate-cake.webm"
MP4_FIXTURE = FIXTURES / "chocolate-cake.mp4"

# The length of the recorded phrase, in seconds.
FIXTURE_SECONDS = 1.66


class FakeWhisperServer:
    """Stand-in for the managed whisper-server process."""

    def __init__(self):
        self.ensure_calls = 0
        self.started = 0
        self.stopped = 0
        self._running = False

    def ensure_running(self):
        self.ensure_calls += 1
        if not self._running:
            self.started += 1
            self._running = True
        return self

    @property
    def base_url(self):
        return "http://127.0.0.1:9"

    def stop(self):
        self.stopped += 1


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


# ----- Transcribing ----- #


def test_transcribe_posts_the_decoded_wav_to_the_server(monkeypatch: pytest.MonkeyPatch):
    server = FakeWhisperServer()
    transcriber = Transcriber(server=server)
    posted = {}

    def fake_post_inference(base_url, wav_audio, file_name="recording.wav"):
        posted["base_url"] = base_url
        posted["wav_audio"] = wav_audio
        return "chocolate cake"

    monkeypatch.setattr("recipeserver.transcriber.post_inference", fake_post_inference)

    text = transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert text == "chocolate cake"
    assert posted["base_url"] == "http://127.0.0.1:9"
    rate, channels, sampwidth, frames = _read_wav(posted["wav_audio"])
    assert (rate, channels, sampwidth) == (SAMPLE_RATE, 1, 2)
    assert frames > 0
    assert server.started == 1


def test_transcribe_starts_the_server_once(monkeypatch: pytest.MonkeyPatch):
    server = FakeWhisperServer()
    transcriber = Transcriber(server=server)

    monkeypatch.setattr("recipeserver.transcriber.post_inference", lambda _url, _wav, file_name="recording.wav": "chocolate cake")

    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")
    transcriber.transcribe(WEBM_FIXTURE.read_bytes(), suffix=".webm")

    assert server.ensure_calls == 2
    assert server.started == 1


def test_transcribe_rejects_an_empty_recording():
    transcriber = Transcriber(server=FakeWhisperServer())

    with pytest.raises(ValueError):
        transcriber.transcribe(b"", suffix=".webm")


def test_transcribe_reports_a_recording_it_cannot_decode():
    transcriber = Transcriber(server=FakeWhisperServer())

    with pytest.raises(TranscriptionError):
        transcriber.transcribe(b"not audio", suffix=".webm")


def test_stop_stops_the_managed_server():
    server = FakeWhisperServer()
    transcriber = Transcriber(server=server)

    transcriber.stop()

    assert server.stopped == 1


# ----- The HTTP client ----- #


def test_post_inference_sends_multipart_form_data(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["content_type"] = request.headers["Content-type"]
        return FakeResponse(json.dumps({"text": "chocolate cake"}).encode("utf-8"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    assert post_inference("http://127.0.0.1:1234", b"RIFF-wav-bytes") == "chocolate cake"
    assert captured["url"] == "http://127.0.0.1:1234/inference"
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="recording.wav"' in captured["body"]
    assert b"RIFF-wav-bytes" in captured["body"]
    assert b'name="response_format"' in captured["body"]
    assert b"json" in captured["body"]


def test_post_inference_surfaces_the_servers_error_message(monkeypatch: pytest.MonkeyPatch):
    from urllib.error import HTTPError

    def fake_urlopen(request, timeout=0):
        raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(b"Invalid request"))

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable) as error:
        post_inference("http://127.0.0.1:1234", b"RIFF-wav-bytes")

    assert "400" in str(error.value)
    assert "Invalid request" in str(error.value)


def test_post_inference_reports_an_unreachable_server(monkeypatch: pytest.MonkeyPatch):
    from urllib.error import URLError

    def fake_urlopen(request, timeout=0):
        raise URLError("Connection refused")

    monkeypatch.setattr("recipeserver.transcriber.urlopen", fake_urlopen)

    with pytest.raises(TranscriberUnavailable):
        post_inference("http://127.0.0.1:1234", b"RIFF-wav-bytes")


def test_post_inference_rejects_a_response_without_text(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setattr("recipeserver.transcriber.urlopen", lambda request, timeout=0: FakeResponse())

    with pytest.raises(TranscriberUnavailable):
        post_inference("http://127.0.0.1:1234", b"RIFF-wav-bytes")
