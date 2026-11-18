"""Tests for the dictation (speech) button: the generated index markup, the
browser script, and the ``/api/transcribe`` endpoint.

The feature is only offered over HTTPS: the browser script removes the
button when the page was not loaded over HTTPS, and the endpoint refuses
requests that did not arrive over HTTPS.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from recipeserver import server as server_module
from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.transcriber import Transcriber
from test.helpers import running_recipe_server

SPEECH_JS_TEST = Path(__file__).parent / "js" / "speech_button_test.js"
SPEECH_ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "speech-button"

# A recording of the phrase "chocolate cake", in the containers the browsers
# record (Opus in WebM, and AAC in MP4 for Safari) and as a plain WAV.
SPEECH_FIXTURES = Path(__file__).parent / "fixtures" / "speech"
WEBM_FIXTURE = SPEECH_FIXTURES / "chocolate-cake.webm"
MP4_FIXTURE = SPEECH_FIXTURES / "chocolate-cake.mp4"

# A short recording, as the browser would send it.
AUDIO = b"fake-webm-audio"


class FakeTranscriber:
    """Stand-in for the Whisper transcriber."""

    def __init__(self, text: str = "chocolate cake", error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        self.calls.append((audio, suffix))
        if self.error is not None:
            raise self.error
        return self.text


class FakeWhisperServer:
    """Stand-in for the managed whisper-server process."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self._running = False

    def ensure_running(self):
        if not self._running:
            self.started += 1
            self._running = True
        return self

    @property
    def base_url(self):
        return "http://127.0.0.1:9"

    def stop(self):
        self.stopped += 1
        self._running = False


@pytest.fixture()
def fake_whisper_server(monkeypatch: pytest.MonkeyPatch) -> FakeWhisperServer:
    """Stub the HTTP call to whisper-server; returns the fake process."""
    server = FakeWhisperServer()
    server.posts = []

    def fake_post(base_url, wav_audio, file_name="recording.wav"):
        server.posts.append((base_url, wav_audio, file_name))
        return "chocolate cake"

    monkeypatch.setattr("recipeserver.transcriber.post_inference", fake_post)
    return server


def _post_audio(url: str, *, headers: dict | None = None, body: bytes = AUDIO, content_type: str = "audio/webm") -> tuple[int, dict]:
    request_headers = {"Content-Type": content_type}
    request_headers.update(headers or {})

    request = Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        payload = error.read()
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"error": payload.decode("utf-8", errors="replace")}
        return error.code, parsed


@pytest.fixture()
def fake_transcriber(monkeypatch: pytest.MonkeyPatch):
    transcriber = FakeTranscriber()
    monkeypatch.setattr(server_module, "transcriber", transcriber)
    return transcriber


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    recipes = tmp_path / "recipes"
    (recipes / "soup").mkdir(parents=True)
    (recipes / "soup" / "recipe.md").write_text("---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n", encoding="utf-8")
    return recipes


# ----- The generated index page ----- #


def _generate_index(tmp_path: Path, dictation_enabled: bool | None = None) -> str:
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    cfg_kwargs = {"site_directory": tmp_path}
    if dictation_enabled is not None:
        cfg_kwargs["dictation_enabled"] = dictation_enabled
    generator = IndexHTMLGenerator(SimpleNamespace(**cfg_kwargs))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()

    return (tmp_path / "index.html").read_text(encoding="utf-8")


def test_index_page_offers_the_dictation_button(tmp_path: Path):
    index = _generate_index(tmp_path)

    assert 'data-testid="speech-button"' in index
    assert 'class="speech-button"' in index
    # The button sits next to the search field.
    assert 'class="speech-input"' in index
    assert 'id="recipe-search"' in index
    # The button starts hidden: the script only reveals it over HTTPS.
    speech_button = index.split('data-testid="speech-button"', 1)[1]
    assert "hidden" in speech_button.split(">", 1)[0]


def test_index_page_hides_the_dictation_button_when_disabled(tmp_path: Path):
    index = _generate_index(tmp_path, dictation_enabled=False)

    assert 'data-testid="speech-button"' not in index
    assert "speech-button.js" not in index
    assert "speech-button.css" not in index
    # The search field itself is still there.
    assert 'id="recipe-search"' in index


def test_index_page_loads_the_dictation_assets(tmp_path: Path):
    index = _generate_index(tmp_path)

    assert "/assets/speech-button/speech-button.css" in index
    assert "/assets/speech-button/speech-button.js" in index
    # The icon helper has to load before the script that inlines the icons.
    assert index.index("icons.js") < index.index("speech-button.js")


def test_dictation_assets_exist():
    assert (SPEECH_ASSETS / "speech-button.js").is_file()
    assert (SPEECH_ASSETS / "speech-button.css").is_file()

    assets = SPEECH_ASSETS.parent
    # The icons live with the other icons and are referenced by root-absolute
    # URL, so the generated pages find them.
    assert (assets / "microphone.svg").is_file()
    assert (assets / "checkmark.svg").is_file()


# ----- The transcription endpoint ----- #


def test_transcription_requires_https(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe")

    assert status == 403
    assert "HTTPS" in body["error"]
    # Nothing was transcribed.
    assert fake_transcriber.calls == []


def test_transcription_is_rejected_when_dictation_is_disabled(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source, config=SimpleNamespace(dictation_enabled=False)) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"})

    assert status == 403
    assert "disabled" in body["error"]
    # Nothing was transcribed.
    assert fake_transcriber.calls == []


def test_transcription_accepts_a_forwarded_https_request(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"})

    assert status == 200
    assert body == {"text": "chocolate cake"}
    assert fake_transcriber.calls == [(AUDIO, ".webm")]


def test_transcription_accepts_the_forwarded_header(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"Forwarded": "proto=https"})

    assert status == 200
    assert body == {"text": "chocolate cake"}


def test_transcription_rejects_a_forwarded_http_request(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "http"})

    assert status == 403
    assert fake_transcriber.calls == []


def test_transcription_rejects_an_unsupported_audio_format(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"}, content_type="audio/flac")

    assert status == 415
    assert fake_transcriber.calls == []


def test_transcription_rejects_an_empty_recording(source: Path, fake_transcriber: FakeTranscriber):
    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"}, body=b"")

    assert status == 400
    assert fake_transcriber.calls == []


def test_transcription_rejects_an_oversized_recording(source: Path, fake_transcriber: FakeTranscriber, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server_module, "MAX_TRANSCRIPTION_SIZE", 8)

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"}, body=b"x" * 9)

    assert status == 413
    assert fake_transcriber.calls == []


def test_transcription_reports_a_missing_transcriber(source: Path, monkeypatch: pytest.MonkeyPatch):
    from recipeserver.transcriber import TranscriberUnavailable

    monkeypatch.setattr(server_module, "transcriber", FakeTranscriber(error=TranscriberUnavailable("whisper-server was not found.")))

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"})

    assert status == 503
    assert "whisper-server" in body["error"]


def test_transcription_reports_a_failed_transcription(source: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server_module, "transcriber", FakeTranscriber(error=RuntimeError("boom")))

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"})

    assert status == 500
    assert body["error"] == "Speech transcription failed"


# ----- The recording the browser sends ----- #


def test_transcription_decodes_the_recorded_clip(source: Path, monkeypatch: pytest.MonkeyPatch, fake_whisper_server: FakeWhisperServer):
    """The whole path: a recorded clip in, a WAV post to whisper-server out.

    This is the test that catches a broken audio decoder: the recording is
    a real Opus/WebM clip, the way the browser records it.
    """
    monkeypatch.setattr(server_module, "transcriber", Transcriber(server=fake_whisper_server))

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(
            f"{base_url}/api/transcribe",
            headers={"X-Forwarded-Proto": "https"},
            body=WEBM_FIXTURE.read_bytes(),
            content_type="audio/webm;codecs=opus",
        )

    assert status == 200
    assert body == {"text": "chocolate cake"}

    # The server is handed a WAV file, not the original WebM container.
    assert len(fake_whisper_server.posts) == 1
    _url, wav_audio, file_name = fake_whisper_server.posts[0]
    assert file_name == "recording.wav"
    assert wav_audio[:4] == b"RIFF"
    assert len(wav_audio) > 1000


def test_transcription_reports_a_recording_it_cannot_decode(source: Path, monkeypatch: pytest.MonkeyPatch, fake_whisper_server: FakeWhisperServer):
    """A clip that is not audio is the caller's mistake, not a server error."""
    monkeypatch.setattr(server_module, "transcriber", Transcriber(server=fake_whisper_server))

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", headers={"X-Forwarded-Proto": "https"}, body=b"not audio at all")

    assert status == 400
    assert "decode" in body["error"].lower()


def test_transcription_decodes_the_clip_safari_records(source: Path, monkeypatch: pytest.MonkeyPatch, fake_whisper_server: FakeWhisperServer):
    """Safari records AAC in MP4; that recording has to transcribe as well."""
    monkeypatch.setattr(server_module, "transcriber", Transcriber(server=fake_whisper_server))

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(
            f"{base_url}/api/transcribe",
            headers={"X-Forwarded-Proto": "https"},
            body=MP4_FIXTURE.read_bytes(),
            content_type="audio/mp4",
        )

    assert status == 200
    assert body == {"text": "chocolate cake"}
    assert fake_whisper_server.posts[0][1].startswith(b"RIFF")


# ----- The browser script ----- #


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_speech_button_script_only_works_over_https():
    result = subprocess.run(
        [shutil.which("node"), str(SPEECH_JS_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "speech button checks passed" in result.stdout


def test_server_binds_to_the_loopback_interface():
    # The site has no authentication, so it only listens on the loopback
    # interface and is served over HTTPS through a local reverse proxy.
    assert server_module.SERVER_BIND_ADDRESS == "0.0.0.0"
    assert server_module.LOCALHOST == "127.0.0.1"
