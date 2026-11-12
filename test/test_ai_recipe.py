from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import socket
from threading import Thread
from types import SimpleNamespace
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from recipeserver.ai_recipe import (
    _ThinkingStreamFilter,
    _metrics_from_ollama_payload,
    _parse_chat_payload,
    _split_embedded_thinking,
    is_model_loaded,
    normalize_ollama_base_url,
    ollama_chat_url,
    ollama_ps_url,
    ollama_tags_url,
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

MODEL_NAMES = (
    "test-model",
    "vision-model",
    "reasoning-model",
    "parts-model",
    "thinking-model",
)

# Ollama reports timings in nanoseconds.
METRICS = {
    "total_duration": 4_000_000_000,
    "load_duration": 1_500_000_000,
    "prompt_eval_count": 50,
    "prompt_eval_duration": 500_000_000,
    "eval_count": 100,
    "eval_duration": 2_000_000_000,
}


def chunks(text: str, size: int) -> Iterator[str]:
    for index in range(0, len(text), size):
        yield text[index : index + size]


class FakeOllamaAPIHandler(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, format, *args):
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send_json(200, {"models": [{"name": f"{name}:latest"} for name in MODEL_NAMES]})
            return

        if self.path == "/api/ps":
            loaded = type(self).state.get("loaded_models", [])
            self._send_json(200, {"models": [{"name": name} for name in loaded]})
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
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).state.setdefault("payloads", []).append(payload)
        type(self).state["payload"] = payload
        model = payload.get("model")

        if payload.get("stream") is True:
            self._stream_chat(model)
        else:
            self._send_json(200, self._chat_payload(model))

    def _chat_payload(self, model: str) -> dict:
        if model == "vision-model":
            message = {"role": "assistant", "content": "Brownies: 1 cup sugar, 2 eggs, 1/2 cup butter."}
            done_reason = "stop"
        elif model == "reasoning-model":
            message = {"role": "assistant", "content": "", "thinking": "still thinking " * 100}
            done_reason = "length"
        elif model == "parts-model":
            message = {"role": "assistant", "content": [{"type": "text", "text": MODEL_OUTPUT}]}
            done_reason = "stop"
        elif model == "thinking-model":
            message = {
                "role": "assistant",
                "content": MODEL_OUTPUT,
                "thinking": "Considering the ingredients.",
            }
            done_reason = "stop"
        else:
            message = {"role": "assistant", "content": MODEL_OUTPUT}
            done_reason = "stop"

        return {
            "model": model,
            "message": message,
            "done": True,
            "done_reason": done_reason,
            **METRICS,
        }

    def _stream_chat(self, model: str):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if model == "reasoning-model":
            for chunk in ("still ", "thinking ", "forever"):
                self._write_line(
                    {
                        "model": model,
                        "message": {"role": "assistant", "content": "", "thinking": chunk},
                        "done": False,
                    }
                )
            self._write_line(
                {
                    "model": model,
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "length",
                    **METRICS,
                }
            )
            return

        if model == "thinking-model":
            for chunk in ("Considering ", "the ingredients."):
                self._write_line(
                    {
                        "model": model,
                        "message": {"role": "assistant", "content": "", "thinking": chunk},
                        "done": False,
                    }
                )

        if model == "vision-model":
            content = "Brownies: 1 cup sugar, 2 eggs, 1/2 cup butter."
        else:
            content = MODEL_OUTPUT

        for chunk in chunks(content, 12):
            self._write_line(
                {
                    "model": model,
                    "message": {"role": "assistant", "content": chunk},
                    "done": False,
                }
            )

        self._write_line(
            {
                "model": model,
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                **METRICS,
            }
        )

    def _write_line(self, payload: dict):
        self.wfile.write(json.dumps(payload).encode("utf-8") + b"\n")
        self.wfile.flush()


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


def read_sse_events(response) -> list[dict]:
    events = []
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def request_ai_events(url: str, payload: dict) -> tuple[int, list[dict], str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request) as response:
        return response.status, read_sse_events(response), response.headers.get_content_type()


def request_ai_raw(url: str, payload: dict) -> str:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request) as response:
        return response.read().decode("utf-8")


def request_ai_image_events(url: str, images: list[tuple[str, bytes]]) -> tuple[int, list[dict]]:
    import uuid

    boundary = f"----RecipeServerTest{uuid.uuid4().hex}"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="inputType"\r\n\r\n'
            "image\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="stream"\r\n\r\n'
            "true\r\n"
        ).encode()
    ]
    for filename, image_bytes in images:
        headers = f"--{boundary}\r\n" f'Content-Disposition: form-data; name="images"; filename="{filename}"\r\n' "Content-Type: image/png\r\n\r\n"
        parts.append(headers.encode() + image_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    request = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urlopen(request) as response:
            return response.status, read_sse_events(response)
    except HTTPError as error:
        return error.code, json.loads(error.read())


@contextmanager
def running_model_api() -> Iterator[tuple[str, dict]]:
    FakeOllamaAPIHandler.state = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaAPIHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", FakeOllamaAPIHandler.state
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


def config_for(model_url: str, **overrides) -> SimpleNamespace:
    values = {
        "model_endpoint": model_url,
        "all_purpose_model_name": "test-model",
        "image_analysis_model": "vision-model",
        "new_recipe_prompt": "ONLY reply with the markdown file.",
        "new_recipe_from_image_prompt": "Transcribe the recipe image.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def status_states(events: list[dict]) -> list[str]:
    return [event["state"] for event in events if event["type"] == "status"]


def test_ai_status_and_generation_from_text(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, body = request_json(f"{base_url}/api/ai-status")
            assert status == 200
            assert body == {
                "configured": True,
                "available": True,
                "model": "test-model",
                "all_purpose_model": "test-model",
                "image_model": "vision-model",
                "image_configured": True,
                "image_available": True,
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
    assert result["metrics"]["model_load_seconds"] == 1.5
    assert result["metrics"]["generation_seconds"] == 2.0
    assert result["metrics"]["token_count"] == 100
    assert result["metrics"]["tokens_per_second"] == 50.0

    payload = model_state["payload"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.2
    assert payload["options"]["num_predict"] == 8192
    assert payload["messages"][0] == {
        "role": "system",
        "content": "ONLY reply with the markdown file.",
    }
    assert "Recipe text:\n1 cup sugar and 2 eggs" in payload["messages"][1]["content"]


def test_ai_generation_streams_normalized_sse_events(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, _model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, events, content_type = request_ai_events(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar and 2 eggs", "stream": True},
            )

    assert status == 200
    assert content_type == "text/event-stream"

    states = status_states(events)
    assert states[0] == "checking_model"
    assert "loading_model" in states
    assert "generating" in states
    assert states[-1] == "complete"

    # The generated Markdown is delivered once in the result event; there is
    # no separate content or thinking event for the browser to render.
    assert all(event["type"] not in {"content", "thinking"} for event in events)

    metrics_event = next(event for event in events if event["type"] == "metrics")
    assert metrics_event["metrics"]["model_load_seconds"] == 1.5
    assert metrics_event["metrics"]["generation_seconds"] == 2.0
    assert metrics_event["metrics"]["token_count"] == 100
    assert metrics_event["metrics"]["tokens_per_second"] == 50.0

    result_event = events[-1]
    assert result_event["type"] == "result"
    assert result_event["result"]["content"].startswith("# Brownies")
    assert result_event["result"]["metrics"] == metrics_event["metrics"]


def test_ai_generation_uses_named_server_sent_events(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, _model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            raw = request_ai_raw(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar", "stream": True},
            )

    assert "event: status\n" in raw
    assert "event: metrics\n" in raw
    assert "event: result\n" in raw
    assert "event: content\n" not in raw
    assert "event: thinking\n" not in raw
    assert "data: {" in raw
    assert raw.endswith("\n\n")


def test_ai_generation_skips_loading_when_model_is_already_loaded(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        model_state["loaded_models"] = ["test-model:latest"]
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, events, _ = request_ai_events(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar", "stream": True},
            )

    assert status == 200
    states = status_states(events)
    assert "loading_model" not in states
    assert states.index("generating") < states.index("complete")


def test_ai_thinking_reports_a_status_without_streaming_text(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        model_state["loaded_models"] = ["thinking-model:latest"]
        with running_recipe_server(source, config_for(model_url, all_purpose_model_name="thinking-model")) as base_url:
            status, events, _ = request_ai_events(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar", "stream": True},
            )

    assert status == 200
    states = status_states(events)
    assert "thinking" in states
    # Content generation resumes after the thinking phase, but the reasoning
    # text is never sent to the browser.
    last_generating = max(index for index, state in enumerate(states) if state == "generating")
    assert states.index("thinking") < last_generating
    assert all(event["type"] != "thinking" for event in events)

    result_event = events[-1]
    assert result_event["type"] == "result"
    assert result_event["result"]["content"].startswith("# Brownies")
    assert "Considering" not in result_event["result"]["content"]


def test_ai_generation_from_url_fetches_page_and_populates_source(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, model_state):
        article_url = f"{model_url}/article"

        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, events, _ = request_ai_events(
                f"{base_url}/api/ai-recipe",
                {"inputType": "url", "input": article_url, "stream": True},
            )

    result_event = events[-1]
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

    messages = [event["message"] for event in events if event["type"] == "status"]
    assert messages[0] == "Checking model status..."
    assert f"Fetching recipe page: {article_url}" in messages
    assert any("Page fetched" in message for message in messages)
    assert any("Generating recipe with test-model" in message for message in messages)
    assert messages[-1] == "Generation complete."


def test_ai_generation_from_image_transcribes_then_drafts(tmp_path):
    from io import BytesIO

    from PIL import Image

    source = tmp_path / "recipes"
    source.mkdir()

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    with running_model_api() as (model_url, model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, events = request_ai_image_events(f"{base_url}/api/ai-recipe", [("recipe.png", image_bytes)])

    result_event = events[-1]
    assert result_event["type"] == "result"
    result = result_event["result"]
    assert status == 200
    assert result["content"].startswith("# Brownies")
    assert result["metadata"]["source"] == {
        "author": None,
        "title": "test-model",
        "format": "AI",
        "url": None,
    }

    payloads = model_state["payloads"]
    assert len(payloads) == 2
    # First call: image analysis model, image prompt + image data URI.
    assert payloads[0]["model"] == "vision-model"
    assert payloads[0]["stream"] is False
    assert payloads[0]["messages"][0] == {
        "role": "system",
        "content": "Transcribe the recipe image.",
    }
    image_content = payloads[0]["messages"][1]["content"]
    assert isinstance(image_content, list)
    assert image_content[1]["type"] == "image_url"
    assert image_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # Second call: all-purpose model drafts from the transcription.
    assert payloads[1]["model"] == "test-model"
    assert payloads[1]["stream"] is True
    assert payloads[1]["messages"][0]["content"] == "ONLY reply with the markdown file."
    assert "transcribed from image" in payloads[1]["messages"][1]["content"]
    assert "1 cup sugar, 2 eggs" in payloads[1]["messages"][1]["content"]

    messages = [event["message"] for event in events if event["type"] == "status"]
    assert any("for transcription" in message for message in messages)
    assert any("Transcribed image." in message for message in messages)


def test_ai_generation_from_multiple_images_keeps_upload_order(tmp_path):
    from io import BytesIO

    from PIL import Image

    source = tmp_path / "recipes"
    source.mkdir()

    def png_bytes(color: str, size: tuple[int, int]) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", size, color=color).save(buffer, format="PNG")
        return buffer.getvalue()

    page_one = png_bytes("white", (8, 8))
    page_two = png_bytes("red", (16, 16))
    images = [("page-one.png", page_one), ("page-two.png", page_two)]

    with running_model_api() as (model_url, model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, events = request_ai_image_events(f"{base_url}/api/ai-recipe", images)

    assert status == 200
    result_event = events[-1]
    assert result_event["type"] == "result"
    assert result_event["result"]["content"].startswith("# Brownies")

    # One transcription per image, in upload order, then a single draft.
    payloads = model_state["payloads"]
    assert [payload["model"] for payload in payloads] == ["vision-model", "vision-model", "test-model"]

    for index, (_filename, image_bytes) in enumerate(images):
        data_uri = payloads[index]["messages"][1]["content"][1]["image_url"]["url"]
        assert data_uri == f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"

    draft_content = payloads[2]["messages"][1]["content"]
    first = draft_content.index("--- Image 1 of 2: page-one.png ---")
    second = draft_content.index("--- Image 2 of 2: page-two.png ---")
    assert first < second
    assert "Brownies: 1 cup sugar, 2 eggs, 1/2 cup butter." in draft_content

    messages = [event["message"] for event in events if event["type"] == "status"]
    assert any("Preparing 2 recipe images..." in message for message in messages)
    assert any("Sending image 1 of 2 (page-one.png)" in message for message in messages)
    assert any("Sending image 2 of 2 (page-two.png)" in message for message in messages)
    assert any("Transcribed 2 images." in message for message in messages)


def test_ai_image_generation_rejects_images_the_vision_model_cannot_read(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'

    with running_model_api() as (model_url, model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            status, body = request_ai_image_events(f"{base_url}/api/ai-recipe", [("sketch.svg", svg)])

    assert status == 400
    assert "Unsupported image type for AI generation" in body["error"]
    assert model_state.get("payloads", []) == []


def test_ai_image_generation_limits_the_number_of_images(tmp_path):
    from io import BytesIO

    from PIL import Image

    source = tmp_path / "recipes"
    source.mkdir()

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    with running_model_api() as (model_url, model_state):
        with running_recipe_server(source, config_for(model_url)) as base_url:
            images = [(f"page-{index}.png", image_bytes) for index in range(21)]
            status, body = request_ai_image_events(f"{base_url}/api/ai-recipe", images)

    assert status == 400
    assert "no more than 20 images" in body["error"]
    assert model_state.get("payloads", []) == []


def test_ai_reasoning_only_response_reports_token_limit(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, _model_state):
        with running_recipe_server(source, config_for(model_url, all_purpose_model_name="reasoning-model")) as base_url:
            status, body = request_json(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "Some recipe text"},
            )

    assert status == 502
    assert "token limit" in body["error"]
    assert "reasoning" in body["error"]


def test_ai_content_as_parts_is_extracted(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_model_api() as (model_url, _model_state):
        with running_recipe_server(source, config_for(model_url, all_purpose_model_name="parts-model")) as base_url:
            status, result = request_json(
                f"{base_url}/api/ai-recipe",
                {"inputType": "text", "input": "1 cup sugar and 2 eggs"},
            )

    assert status == 200
    assert result["content"].startswith("# Brownies")


def test_ai_endpoints_are_disabled_without_configuration(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = SimpleNamespace(
        model_endpoint="",
        all_purpose_model_name="",
        image_analysis_model="",
        new_recipe_prompt="",
        new_recipe_from_image_prompt="",
    )

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/ai-status")
        assert status == 200
        assert body == {
            "configured": False,
            "available": False,
            "model": "",
            "all_purpose_model": "",
            "image_model": "",
            "image_configured": False,
            "image_available": False,
        }

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
        all_purpose_model_name="test-model",
        image_analysis_model="vision-model",
        new_recipe_prompt="Prompt",
        new_recipe_from_image_prompt="Transcribe the recipe image.",
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
        all_purpose_model_name="test-model",
        image_analysis_model="vision-model",
        new_recipe_prompt="Prompt",
        new_recipe_from_image_prompt="Transcribe the recipe image.",
    )

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "image", "input": "something"},
        )
        assert status == 400
        assert "recipe image" in body["error"]

        status, body = request_json(
            f"{base_url}/api/ai-recipe",
            {"inputType": "text", "input": "   "},
        )
        assert status == 400
        assert "non-empty input" in body["error"]


@pytest.mark.parametrize(
    ("endpoint", "expected_base"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/v1/", "http://localhost:11434"),
        ("http://localhost:11434/v1/chat/completions", "http://localhost:11434"),
        ("http://localhost:11434/chat/completions", "http://localhost:11434"),
        ("http://localhost:11434/api/chat", "http://localhost:11434"),
        ("http://localhost:11434/api/ps", "http://localhost:11434"),
        ("http://localhost:11434/api/tags", "http://localhost:11434"),
        ("http://localhost:11434/api", "http://localhost:11434"),
        ("http://localhost:11434/ollama/api/chat", "http://localhost:11434/ollama"),
        ("http://localhost:11434/custom/path", "http://localhost:11434/custom/path"),
    ],
)
def test_ollama_url_normalization(endpoint, expected_base):
    assert normalize_ollama_base_url(endpoint) == expected_base
    assert ollama_chat_url(endpoint) == f"{expected_base}/api/chat"
    assert ollama_ps_url(endpoint) == f"{expected_base}/api/ps"
    assert ollama_tags_url(endpoint) == f"{expected_base}/api/tags"


def test_loaded_model_detection_uses_api_ps():
    with running_model_api() as (model_url, model_state):
        assert is_model_loaded(model_url, "test-model") is False

        model_state["loaded_models"] = ["test-model:latest"]
        assert is_model_loaded(model_url, "test-model") is True
        assert is_model_loaded(model_url, "other-model") is False


def test_thinking_stream_filter_splits_tags_across_chunks():
    filter_ = _ThinkingStreamFilter()
    content = ""
    thinking = ""

    for chunk in ("<thi", "nk>reason", "ing</thi", "nk>answer"):
        content_chunk, thinking_chunk = filter_.feed(chunk)
        content += content_chunk
        thinking += thinking_chunk

    content_chunk, thinking_chunk = filter_.finish()
    content += content_chunk
    thinking += thinking_chunk

    assert content == "answer"
    assert thinking == "reasoning"


def test_thinking_stream_filter_handles_a_split_right_after_the_tag_name():
    filter_ = _ThinkingStreamFilter()
    content = ""
    thinking = ""

    for chunk in ("<think", ">reason", "</think", ">answer"):
        content_chunk, thinking_chunk = filter_.feed(chunk)
        content += content_chunk
        thinking += thinking_chunk

    content_chunk, thinking_chunk = filter_.finish()
    content += content_chunk
    thinking += thinking_chunk

    assert content == "answer"
    assert thinking == "reason"


def test_thinking_stream_filter_handles_an_opening_tag_with_attributes():
    content, thinking = _split_embedded_thinking('<think type="reason">reason</think>answer')

    assert content == "answer"
    assert thinking == "reason"


def test_thinking_stream_filter_handles_unmatched_closing_tag():
    content, thinking = _split_embedded_thinking("reasoning</think>answer")

    assert content == "answer"
    assert thinking == "reasoning"


def test_metrics_from_ollama_payload_normalizes_nanoseconds():
    metrics = _metrics_from_ollama_payload(METRICS)

    assert metrics == {
        "model_load_seconds": 1.5,
        "generation_seconds": 2.0,
        "total_seconds": 4.0,
        "token_count": 100,
        "prompt_token_count": 50,
        "tokens_per_second": 50.0,
        "prompt_tokens_per_second": 100.0,
    }


def test_parse_chat_payload_separates_thinking_and_content():
    result = _parse_chat_payload(
        {
            "message": {
                "content": "<think>embedded reasoning</think># Brownies",
                "thinking": "separate reasoning",
            },
            "done": True,
            "done_reason": "stop",
            **METRICS,
        }
    )

    assert result.content == "# Brownies"
    assert result.thinking == "separate reasoningembedded reasoning"
    assert result.finish_reason == "stop"
    assert result.metrics["token_count"] == 100


def test_parse_model_output_strips_code_fences_and_front_matter():
    content, metadata = parse_model_output(MODEL_OUTPUT)

    assert content.startswith("# Brownies")
    assert "```" not in content
    assert metadata["meals"] == ["Dessert"]
    assert metadata["categories"] == ["Baking"]


def test_parse_model_output_normalizes_source_format_for_the_editor():
    content, metadata = parse_model_output("---\nsource:\n  format: website\n  title: Example Recipe\n---\n# Example\n")

    assert content.strip() == "# Example"
    assert metadata["source"] == {
        "author": None,
        "title": "Example Recipe",
        "format": "Website",
        "url": None,
    }
