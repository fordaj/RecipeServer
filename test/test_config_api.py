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
from recipeserver.server import RecipeRequestHandler


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
        f"source_directory = {json.dumps(str(source))}\n"
        f"{MODEL_ENDPOINT_KEY} = \"\"\n"
        f'{RECIPE_SERVER_NAME_KEY} = "Test Kitchen"\n',
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
        "food_color",
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
    assert tomllib.loads(config_file.read_text(encoding="UTF-8"))[
        RECIPE_SERVER_NAME_KEY
    ] == "My Kitchen"
    assert regen_calls == [True]


def test_post_config_rejects_invalid_values(config_server):
    base, config, _, regen_calls = config_server

    status, data = _post(base, "/api/config", {"values": {"source_directory": "/no/such/dir"}})

    assert status == 400
    assert "existing directory" in data["error"]
    assert regen_calls == []

    status, data = _post(
        base, "/api/config", {"values": {MODEL_ENDPOINT_KEY: "ftp://host/v1"}}
    )
    assert status == 400
    assert "valid http" in data["error"]

    status, data = _post(base, "/api/config", {"values": {"unknown": "x"}})
    assert status == 400
    assert "Unknown configuration key" in data["error"]


def test_post_config_blank_server_name_falls_back_to_default(config_server):
    base, config, _, _ = config_server

    status, data = _post(
        base, "/api/config", {"values": {RECIPE_SERVER_NAME_KEY: "   "}}
    )

    assert status == 200
    assert data["values"][RECIPE_SERVER_NAME_KEY] == "My Recipe Server"
    assert config.recipe_server_name == "My Recipe Server"
