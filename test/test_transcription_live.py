"""Transcription with the real Ollama Qwen3-ASR model.

These tests require a running Ollama server with the Qwen3-ASR model pulled:

    ollama pull hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0
    RECIPE_SERVER_TEST_OLLAMA=1 uv run pytest test/test_transcription_live.py

Environment variables:

| Variable                      | Default                                   | Purpose                    |
| ----------------------------- | ----------------------------------------- | -------------------------- |
| `RECIPE_SERVER_TEST_OLLAMA`   | unset                                     | Set to `1` to run these.   |
| `RECIPE_SERVER_OLLAMA_URL`    | `http://localhost:11434`                  | The Ollama server to use.  |
| `RECIPE_SERVER_OLLAMA_MODEL`  | `hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0` | The model to transcribe with. |
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recipeserver import server as server_module
from recipeserver.transcriber import Transcriber

FIXTURE = Path(__file__).parent / "fixtures" / "speech" / "chocolate-cake.webm"

pytestmark = pytest.mark.skipif(
    os.environ.get("RECIPE_SERVER_TEST_OLLAMA", "").strip().strip('"').lower() not in {"1", "true", "yes"},
    reason="a running Ollama server with the Qwen3-ASR model is required; set RECIPE_SERVER_TEST_OLLAMA=1 to run these tests",
)


def _endpoint() -> str:
    return os.environ.get("RECIPE_SERVER_OLLAMA_URL", "http://localhost:11434").strip() or "http://localhost:11434"


def _model() -> str:
    return (
        os.environ.get("RECIPE_SERVER_OLLAMA_MODEL", "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0").strip() or "hf.co/ggml-org/Qwen3-ASR-0.6B-GGUF:Q8_0"
    )


@pytest.fixture()
def transcriber():
    return Transcriber()


def test_the_recorded_phrase_is_transcribed(transcriber):
    text = transcriber.transcribe(FIXTURE.read_bytes(), suffix=".webm", endpoint=_endpoint(), model=_model())

    assert "chocolate" in text.lower()
    assert "cake" in text.lower()


def test_the_api_transcribes_the_recorded_phrase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transcriber):
    import json
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    source = tmp_path / "recipes"
    (source / "soup").mkdir(parents=True)
    (source / "soup" / "recipe.md").write_text("---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n", encoding="utf-8")

    monkeypatch.setattr(server_module, "transcriber", transcriber)

    from test.helpers import running_recipe_server

    with running_recipe_server(source) as (base_url, _, _):
        request = Request(
            f"{base_url}/api/transcribe",
            data=FIXTURE.read_bytes(),
            headers={"Content-Type": "audio/webm;codecs=opus", "X-Forwarded-Proto": "https"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                status, body = response.status, json.loads(response.read())
        except HTTPError as error:
            status, body = error.code, json.loads(error.read())

    assert status == 200
    assert "chocolate" in body["text"].lower()
    assert "cake" in body["text"].lower()


def test_the_bundled_test_sample_is_transcribed(transcriber):
    """The sample the Configuration dialog's Test button posts must work."""
    sample = Path(server_module.TRANSCRIPTION_TEST_SAMPLE_PATH).read_bytes()

    text = transcriber.transcribe(sample, suffix=".wav", endpoint=_endpoint(), model=_model())

    assert "two cups of flour" in text.lower()
