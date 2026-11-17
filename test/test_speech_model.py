"""Transcription with the real whisper-server.

These tests download the ggml model weights (about 75 MB for "tiny"), so
they only run when they are asked for:

    RECIPE_SERVER_TEST_WHISPER=1 uv run pytest test/test_speech_model.py

Set ``RECIPE_SERVER_TEST_WHISPER_MODEL`` to use another model size, and
``RECIPE_SERVER_WHISPER_MODEL_DIR`` to keep the downloaded weights out of
the user data directory. The test machine must be able to reach
huggingface.co and run the bundled whisper-server for this platform.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from recipeserver import server as server_module
from recipeserver.transcriber import Transcriber

FIXTURE = Path(__file__).parent / "fixtures" / "speech" / "chocolate-cake.webm"

pytestmark = pytest.mark.skipif(
    os.environ.get("RECIPE_SERVER_TEST_WHISPER", "").strip().lower() not in {"1", "true", "yes"},
    reason="the Whisper model has to be downloaded first; set RECIPE_SERVER_TEST_WHISPER=1 to run these tests",
)


def _model_name() -> str:
    return os.environ.get("RECIPE_SERVER_TEST_WHISPER_MODEL", "tiny").strip() or "tiny"


def _post_audio(url: str, body: bytes) -> tuple[int, dict]:
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "audio/webm;codecs=opus", "X-Forwarded-Proto": "https"},
        method="POST",
    )
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
def transcriber():
    instance = Transcriber(model=_model_name())
    yield instance
    instance.stop()


def test_the_recorded_phrase_is_transcribed(transcriber):
    text = transcriber.transcribe(FIXTURE.read_bytes(), suffix=".webm")

    assert "chocolate" in text.lower()
    assert "cake" in text.lower()


def test_the_api_transcribes_the_recorded_phrase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transcriber):
    source = tmp_path / "recipes"
    (source / "soup").mkdir(parents=True)
    (source / "soup" / "recipe.md").write_text("---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n", encoding="utf-8")

    monkeypatch.setattr(server_module, "transcriber", transcriber)

    from test.helpers import running_recipe_server

    with running_recipe_server(source) as (base_url, _, _):
        status, body = _post_audio(f"{base_url}/api/transcribe", FIXTURE.read_bytes())

    assert status == 200
    assert "chocolate" in body["text"].lower()
