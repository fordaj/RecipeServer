import json
import tomllib
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from recipeserver.config import (
    CONFIG_FILENAME,
    MODEL_ENDPOINT_KEY,
    RECIPE_SERVER_NAME_KEY,
    Configuration,
)
import recipeserver.server as server_module
from recipeserver.server import RecipeRequestHandler
from recipeserver.transcriber import TranscriberUnavailable


@pytest.fixture
def config_server(tmp_path, monkeypatch):
    """Live server with a real Configuration backed by a tmp TOML file."""
    source = tmp_path / "source"
    (source / "Cake").mkdir(parents=True)
    (source / "Cake" / "recipe.md").write_text("# Cake\n", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>Index</h1>", encoding="utf-8")

    config_file = tmp_path / CONFIG_FILENAME
    config_file.write_text(
        f"source_directory = {json.dumps(str(source))}\n" f'{MODEL_ENDPOINT_KEY} = ""\n' f'{RECIPE_SERVER_NAME_KEY} = "Test Kitchen"\n',
        encoding="UTF-8",
    )

    def unexpected_input(prompt=""):
        raise AssertionError("Existing model configuration should not prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)
    config = Configuration()
    config.handle_configuration(config_file)

    regen_calls = []
    handler = partial(
        RecipeRequestHandler,
        directory=str(site),
        source_directory=source,
        on_config_saved=lambda: regen_calls.append(True),
        config=config,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", config, config_file, regen_calls
    finally:
        server.shutdown()
        server.server_close()


def _get(base, path):
    with urlopen(f"{base}{path}") as response:
        return response.status, json.loads(response.read())


def _post(base, path, payload):
    request = Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_get_config_returns_values_and_field_specs(config_server):
    base, config, _, _ = config_server

    status, data = _get(base, "/api/config")

    assert status == 200
    assert data["values"][RECIPE_SERVER_NAME_KEY] == "Test Kitchen"
    assert data["values"][MODEL_ENDPOINT_KEY] == ""
    keys = {field["key"] for field in data["fields"]}
    assert keys == {
        "recipe_server_name",
        "source_directory",
        "model_endpoint",
        "all_purpose_model_name",
        "image_analysis_model",
        "server_port",
        "server_bind_address",
        "food_color",
        "dictation_enabled",
        "transcription_endpoint",
        "transcription_model",
        "transcription_keep_alive",
        "timeline_retention",
    }
    for field in data["fields"]:
        assert field["label"] and (field["help"] or field["input_type"])


def test_post_config_saves_and_triggers_regen(config_server):
    base, config, config_file, regen_calls = config_server

    status, data = _post(
        base,
        "/api/config",
        {"values": {RECIPE_SERVER_NAME_KEY: "My Kitchen"}},
    )

    assert status == 200
    assert data["success"] is True
    assert data["changed"] == [RECIPE_SERVER_NAME_KEY]
    assert data["values"][RECIPE_SERVER_NAME_KEY] == "My Kitchen"
    assert config.recipe_server_name == "My Kitchen"
    assert tomllib.loads(config_file.read_text(encoding="UTF-8"))[RECIPE_SERVER_NAME_KEY] == "My Kitchen"
    assert regen_calls == [True]


def test_post_config_rejects_invalid_values(config_server):
    base, config, _, regen_calls = config_server

    status, data = _post(base, "/api/config", {"values": {"source_directory": "/no/such/dir"}})

    assert status == 400
    assert "existing directory" in data["error"]
    assert regen_calls == []

    status, data = _post(base, "/api/config", {"values": {MODEL_ENDPOINT_KEY: "ftp://host/v1"}})
    assert status == 400
    assert "valid http" in data["error"]

    status, data = _post(base, "/api/config", {"values": {"unknown": "x"}})
    assert status == 400
    assert "Unknown configuration key" in data["error"]


def test_post_config_blank_server_name_falls_back_to_default(config_server):
    base, config, _, _ = config_server

    status, data = _post(base, "/api/config", {"values": {RECIPE_SERVER_NAME_KEY: "   "}})

    assert status == 200
    assert data["values"][RECIPE_SERVER_NAME_KEY] == "My Recipe Server"
    assert config.recipe_server_name == "My Recipe Server"


def test_get_config_reports_timeline_retention_as_a_select(config_server):
    base, _, _, _ = config_server

    status, data = _get(base, "/api/config")

    assert status == 200
    assert data["values"]["timeline_retention"] == "gfs"
    field = next(field for field in data["fields"] if field["key"] == "timeline_retention")
    assert field["input_type"] == "select"
    assert [option["value"] for option in field["options"]] == ["gfs", "unlimited"]


def test_post_config_switches_timeline_retention_and_persists_it(config_server):
    base, config, config_file, regen_calls = config_server

    status, data = _post(base, "/api/config", {"values": {"timeline_retention": "unlimited"}})

    assert status == 200
    assert data["changed"] == ["timeline_retention"]
    assert data["values"]["timeline_retention"] == "unlimited"
    assert config.timeline_retention == "unlimited"
    assert tomllib.loads(config_file.read_text(encoding="UTF-8"))["timeline_retention"] == "unlimited"
    assert regen_calls == [True]

    status, data = _post(base, "/api/config", {"values": {"timeline_retention": "yearly"}})
    assert status == 400
    assert config.timeline_retention == "unlimited"


def test_post_config_test_transcription_runs_the_sample(config_server, monkeypatch):
    base, config, _, _ = config_server
    calls = {}

    class FakeTranscriber:
        def transcribe(self, audio, suffix=".wav", **kwargs):
            calls["suffix"] = suffix
            calls["audio_prefix"] = audio[:4]
            calls.update(kwargs)
            return "Add two cups of flour and one cup of sugar."

    monkeypatch.setattr(server_module, "transcriber", FakeTranscriber())

    status, data = _post(
        base,
        "/api/config/test-transcription",
        {"endpoint": "http://localhost:11434", "model": "custom/audio-model:latest", "keep_alive": "10m"},
    )

    assert status == 200
    assert data["ok"] is True
    assert data["text"] == "Add two cups of flour and one cup of sugar."
    assert isinstance(data["seconds"], (int, float))
    # The unsaved field values from the dialog are used for the test.
    assert calls["endpoint"] == "http://localhost:11434"
    assert calls["model"] == "custom/audio-model:latest"
    assert calls["keep_alive"] == "10m"
    # The bundled sample is a real WAV file.
    assert calls["audio_prefix"] == b"RIFF"


def test_post_config_test_transcription_falls_back_to_saved_config(config_server, monkeypatch):
    base, config, _, _ = config_server

    calls = {}

    class FakeTranscriber:
        def transcribe(self, audio, suffix=".wav", **kwargs):
            calls.update(kwargs)
            return "ok"

    monkeypatch.setattr(server_module, "transcriber", FakeTranscriber())

    status, data = _post(base, "/api/config/test-transcription", {})

    assert status == 200
    assert data["ok"] is True
    assert calls["endpoint"] == "http://localhost:11434"
    assert data["text"] == "ok"


def test_post_config_test_transcription_reports_an_unreachable_server(config_server, monkeypatch):
    base, config, _, _ = config_server

    class UnreachableTranscriber:
        def transcribe(self, audio, suffix=".wav", **kwargs):
            raise TranscriberUnavailable("The Ollama server at http://localhost:11434 is not reachable: Connection refused")

    monkeypatch.setattr(server_module, "transcriber", UnreachableTranscriber())

    status, data = _post(base, "/api/config/test-transcription", {})

    assert status == 503
    assert "not reachable" in data["error"]


def test_post_config_test_transcription_rejects_an_invalid_override(config_server, monkeypatch):
    base, config, _, _ = config_server

    status, data = _post(base, "/api/config/test-transcription", {"endpoint": "ftp://nope"})

    assert status == 400
    assert "valid http" in data["error"]

    status, data = _post(base, "/api/config/test-transcription", {"keep_alive": "forever"})

    assert status == 400
    assert "keep-alive" in data["error"]
