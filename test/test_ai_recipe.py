from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Thread
from types import SimpleNamespace
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from recipeserver.ai_recipe import (
    normalize_chat_completions_url,
    normalize_models_url,
    parse_model_output,
)
from recipeserver.server import RecipeRequestHandler


MODEL_OUTPUT = """```markdown
---
meals:
  - Dessert
categories: Baking
---

# Brownies

![Brownies](image.png)

## Ingredients

- [ ] `1/2 cup` butter
```"""


class FakeModelAPIHandler(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, format, *args):
        pass

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self):
        if self.path == "/v1/models":
            self._send_json(200, {"data": [{"id": "test-model"}]})
            return

        if self.path == "/article":
            page = """<!DOCTYPE html>
<html>
<head><title>Grandma's Brownies</title></head>
<body>
<nav>Navigation</nav>
<main>
<h1>Grandma's Brownies</h1>
<p>Preheat oven to 350 F. Mix 1 cup sugar with 1/2 cup butter.</p>
</main>
</body>
</html>"""
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).state["payload"] = payload
        self._send_json(
            200,
            {"choices": [{"message": {"content": MODEL_OUTPUT}}]},
        )


def request_json(url: str, payload: dict | None = None) -> tuple[int, dict]:
    if payload is None:
        request = Request(url, method="GET")
    else:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def request_ai_events(url: str, payload: dict) -> tuple[int, list[dict]]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request) as response:
        events = [json.loads(line) for line in response]
        return response.status, events


@contextmanager
def running_model_api() -> Iterator[tuple[str, dict]]:
    FakeModelAPIHandler.state = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelAPIHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", FakeModelAPIHandler.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def running_recipe_server(source, config) -> Iterator[str]:
    handler = partial(
        RecipeRequestHandler,
        directory=str(source),
        source_directory=source,
        config=config,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_ai_status_and_generation_from_text(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        config = SimpleNamespace(
            model_endpoint=model_url,
            model_name="test-model",
            new_recipe_prompt="ONLY reply with the markdown file.",
        )

        with running_recipe_server(source, config) as base_url:
            status, body = request_json(f"{base_url}/api/ai-status")
            assert status == 200
            assert body == {
                "configured": True,
                "available": True,
                "model": "test-model",
            }

            status, result = request_json(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar and 2 eggs"},
            )

    assert status == 200
    assert result["content"].startswith("# Brownies")
    assert result["metadata"]["meals"] == ["Dessert"]
    assert result["metadata"]["categories"] == ["Baking"]
    assert result["metadata"]["source"] == {
        "author": None,
        "title": "test-model",
        "format": "AI",
        "url": None,
    }

    payload = model_state["payload"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["messages"][0] == {
        "role": "system",
        "content": "ONLY reply with the markdown file.",
    }
    assert "Recipe text:\n1 cup sugar and 2 eggs" in payload["messages"][1]["content"]


def test_ai_generation_from_url_fetches_page_and_populates_source(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        config = SimpleNamespace(
            model_endpoint=model_url,
            model_name="test-model",
            new_recipe_prompt="Only reply with Markdown.",
        )
        article_url = f"{model_url}/article"

        with running_recipe_server(source, config) as base_url:
            status, events = request_ai_events(
                f"{base_url}/api/ai-recipe",
                {"inputType": "url", "input": article_url, "stream": True},
            )

    result_event = events[-1]
    progress = [event["message"] for event in events if event["type"] == "progress"]
    assert result_event["type"] == "result"
    result = result_event["result"]
    assert status == 200
    assert result["metadata"]["source"] == {
        "author": None,
        "title": "Grandma's Brownies",
        "format": "Website",
        "url": article_url,
    }

    user_message = model_state["payload"]["messages"][1]["content"]
    assert f"Recipe URL: {article_url}" in user_message
    assert "Page title: Grandma's Brownies" in user_message
    assert "Preheat oven to 350 F" in user_message
    assert "Navigation" not in user_message
    assert progress[0] == "Checking the configured AI model..."
    assert f"Fetching recipe page: {article_url}" in progress
    assert any("source URL and extracted text" in message for message in progress)
    assert any("Generating recipe with test-model" in message for message in progress)
    assert progress[-1] == "AI response received. Preparing the recipe draft..."


def test_ai_endpoints_are_disabled_without_configuration(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = SimpleNamespace(model_endpoint="", model_name="", new_recipe_prompt="")

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/ai-status")
        assert status == 200
        assert body == {"configured": False, "available": False, "model": ""}

        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "text", "input": "Some recipe text"},
        )
        assert status == 503
        assert "not configured" in body["error"]


def test_ai_endpoint_reports_unavailable_model(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        unavailable_port = sock.getsockname()[1]

    config = SimpleNamespace(
        model_endpoint=f"http://127.0.0.1:{unavailable_port}/v1",
        model_name="test-model",
        new_recipe_prompt="Prompt",
    )

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/ai-status")
        assert status == 200
        assert body["configured"] is True
        assert body["available"] is False

        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "text", "input": "Some recipe text"},
        )
        assert status == 503
        assert "Could not reach" in body["error"]


def test_ai_recipe_rejects_invalid_requests(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = SimpleNamespace(
        model_endpoint="http://127.0.0.1:1234/v1",
        model_name="test-model",
        new_recipe_prompt="Prompt",
    )

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "image", "input": "something"},
        )
        assert status == 400
        assert "inputType" in body["error"]

        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "text", "input": "   "},
        )
        assert status == 400
        assert "non-empty input" in body["error"]


@pytest.mark.parametrize(
    ("endpoint", "expected_chat_url", "expected_models_url"),
    [
        (
            "http://localhost:11434",
            "http://localhost:11434/v1/chat/completions",
            "http://localhost:11434/v1/models",
        ),
        (
            "http://localhost:1234/v1/",
            "http://localhost:1234/v1/chat/completions",
            "http://localhost:1234/v1/models",
        ),
        (
            "http://localhost:8080/v1/chat/completions",
            "http://localhost:8080/v1/chat/completions",
            "http://localhost:8080/v1/models",
        ),
        (
            "http://localhost:11434/api/chat",
            "http://localhost:11434/api/chat",
            "http://localhost:11434/api/tags",
        ),
    ],
)
def test_model_url_normalization(endpoint, expected_chat_url, expected_models_url):
    assert normalize_chat_completions_url(endpoint) == expected_chat_url
    assert normalize_models_url(endpoint) == expected_models_url


def test_parse_model_output_strips_code_fences_and_front_matter():
    content, metadata = parse_model_output(MODEL_OUTPUT)

    assert content.startswith("# Brownies")
    assert "```" not in content
    assert metadata["meals"] == ["Dessert"]
    assert metadata["categories"] == ["Baking"]


def test_parse_model_output_normalizes_source_format_for_the_editor():
    content, metadata = parse_model_output(
        "---\nsource:\n  format: website\n  title: Example Recipe\n---\n# Example\n"
    )

    assert content.strip() == "# Example"
    assert metadata["source"] == {
        "author": None,
        "title": "Example Recipe",
        "format": "Website",
        "url": None,
    }
