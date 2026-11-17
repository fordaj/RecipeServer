import json
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from typing import Iterator
from urllib.request import Request, urlopen

import frontmatter

from .helpers import request_json, running_recipe_server, write_recipe

METRICS = {
    "total_duration": 4_000_000_000,
    "load_duration": 1_500_000_000,
    "prompt_eval_count": 50,
    "prompt_eval_duration": 500_000_000,
    "eval_count": 100,
    "eval_duration": 2_000_000_000,
}

MODEL_NAMES = ("test-model", "vision-model")

RECIPE_FRONT_MATTER = "meals:\n  - Dinner\ncontributor: Andrew\ncreatedOn: 2020-05-01\n"
OTHER_RECIPE_FRONT_MATTER = "meals:\n  - Lunch\n"


def config_for(model_url: str, **overrides):
    values = {
        "model_endpoint": model_url,
        "all_purpose_model_name": "test-model",
        "image_analysis_model": "vision-model",
        "new_recipe_prompt": "ONLY reply with the markdown file.",
        "new_recipe_from_image_prompt": "Transcribe the recipe image.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def content_response(text: str) -> dict:
    return {
        "model": "test-model",
        "message": {"role": "assistant", "content": text},
        "done": True,
        "done_reason": "stop",
        **METRICS,
    }


def tool_call_response(name: str, arguments, content: str = "") -> dict:
    return {
        "model": "test-model",
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        },
        "done": True,
        "done_reason": "stop",
        **METRICS,
    }


class FakeAssistantModelHandler(BaseHTTPRequestHandler):
    """A fake Ollama server that plays back a scripted queue of responses."""

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
            self._send_json(200, {"models": [{"name": "test-model:latest"}]})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).state.setdefault("payloads", []).append(payload)
        type(self).state.setdefault("payload", payload)

        responses = type(self).state.setdefault("responses", [])
        if responses:
            self._send_json(200, responses.pop(0))
            return

        self._send_json(200, content_response("There are 16 tablespoons in a cup."))


@contextmanager
def running_assistant_model(**state) -> Iterator[tuple[str, dict]]:
    handler_class = type("FakeAssistantModel", (FakeAssistantModelHandler,), {"state": dict(state)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", handler_class.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def read_recipe_file(path):
    return frontmatter.loads(path.read_text(encoding="utf-8"))


def test_assistant_answers_general_questions(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "dinners" / "pasta" / "recipe.md", RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")

    with running_assistant_model() as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "How many tablespoons are in a cup?", "stream": False},
            )

    assert status == 200
    assert body["reply"] == "There are 16 tablespoons in a cup."
    assert body["edited"] is False

    payload = model_state["payload"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    # The index page offers no editing tool.
    tool_names = [tool["function"]["name"] for tool in payload["tools"]]
    assert "read_recipe" in tool_names
    assert "list_recipes" in tool_names
    assert "update_current_recipe" not in tool_names


def test_assistant_edits_current_recipe(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "dinners" / "pasta" / "recipe.md"
    write_recipe(recipe, RECIPE_FRONT_MATTER, "# Pasta\n\n`2 tbsp` salt.\n")

    new_body = "# Pasta\n\n`1 tbsp` salt.\n"
    responses = [
        tool_call_response("update_current_recipe", {"content": new_body}),
        content_response("Done — I halved the salt."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Adjust the recipe to use half as much salt", "path": "dinners/pasta/recipe.md", "stream": False},
            )

    assert status == 200
    assert body["edited"] is True
    assert body["path"] == "dinners/pasta/recipe.md"
    assert body["reply"] == "Done — I halved the salt."
    assert [path.resolve() for path in saved] == [recipe.resolve()]

    post = read_recipe_file(recipe)
    assert post.content.strip() == "# Pasta\n\n`1 tbsp` salt."
    # The front matter is preserved and updatedOn is refreshed by the server.
    assert post.metadata["meals"] == ["Dinner"]
    assert post.metadata["contributor"] == "Andrew"
    assert post.metadata["createdOn"].isoformat() == "2020-05-01"
    assert post.metadata["updatedOn"]

    # The recipe page offers the update tool.
    first_payload = model_state["payloads"][0]
    tool_names = [tool["function"]["name"] for tool in first_payload["tools"]]
    assert "update_current_recipe" in tool_names


def test_assistant_rejects_server_managed_metadata_field(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "dinners" / "pasta" / "recipe.md"
    original = f"---\n{RECIPE_FRONT_MATTER}---\n# Pasta\n\nBody.\n"
    write_recipe(recipe, RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")

    responses = [
        tool_call_response("update_current_recipe", {"content": "# Pasta\n\nBody.\n", "metadata": {"updatedOn": "2000-01-01"}}),
        content_response("That field is managed by the server; the rest stands."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Set the edit date", "path": "dinners/pasta/recipe.md"},
            )

    assert status == 200
    assert body["edited"] is False
    assert saved == []
    assert recipe.read_text(encoding="utf-8") == original
    tool_message = model_state["payloads"][1]["messages"][-1]
    assert "'updatedOn' is managed by the server" in tool_message["content"]


def test_assistant_applies_partial_metadata_change(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "dinners" / "pasta" / "recipe.md"
    write_recipe(recipe, RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")

    responses = [
        tool_call_response("update_current_recipe", {"content": "# Pasta\n\nBody.\n", "metadata": {"makes": 4}}),
        content_response("It now serves 4."),
    ]

    with running_assistant_model(responses=responses) as (model_url, _model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Make it serve 4 people", "path": "dinners/pasta/recipe.md"},
            )

    assert status == 200
    assert body["edited"] is True
    assert [path.resolve() for path in saved] == [recipe.resolve()]

    post = read_recipe_file(recipe)
    assert post.metadata["makes"] == 4
    assert post.metadata["meals"] == ["Dinner"]


def test_assistant_can_read_other_recipes(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    pasta = source / "dinners" / "pasta" / "recipe.md"
    soup = source / "soups" / "tomato" / "recipe.md"
    write_recipe(pasta, RECIPE_FRONT_MATTER, "# Pasta\n\nTasty.\n")
    write_recipe(soup, OTHER_RECIPE_FRONT_MATTER, "# Tomato Soup\n\nSimmer tomatoes.\n")

    responses = [
        tool_call_response("list_recipes", {}),
        tool_call_response("read_recipe", {"path": "soups/tomato/recipe.md"}),
        content_response("The tomato soup simmers tomatoes."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "What does the tomato soup do?", "path": "dinners/pasta/recipe.md"},
            )

    assert status == 200
    assert body["reply"] == "The tomato soup simmers tomatoes."

    # The tool messages sent back to the model carry the tool results.
    third_payload = model_state["payloads"][2]
    tool_messages = [message for message in third_payload["messages"] if message.get("role") == "tool"]
    assert any("soups/tomato/recipe.md" in message["content"] for message in tool_messages)
    assert any("Simmer tomatoes" in message["content"] for message in tool_messages)


def test_assistant_read_recipe_rejects_paths_outside_the_library(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    responses = [
        tool_call_response("read_recipe", {"path": "../secrets.md"}),
        content_response("I can't read that file."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, _body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Read ../secrets.md"},
            )

    assert status == 200
    third_payload = model_state["payloads"][1]
    tool_messages = [message for message in third_payload["messages"] if message.get("role") == "tool"]
    assert any("source directory" in message["content"] for message in tool_messages)


def test_assistant_edit_is_bound_to_the_page_being_viewed(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    pasta = source / "dinners" / "pasta" / "recipe.md"
    soup = source / "soups" / "tomato" / "recipe.md"
    write_recipe(pasta, RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")
    write_recipe(soup, OTHER_RECIPE_FRONT_MATTER, "# Tomato Soup\n\nBody.\n")

    original_soup = soup.read_text(encoding="utf-8")

    responses = [
        tool_call_response("update_current_recipe", {"content": "# Pasta\n\nHacked.\n"}),
        content_response("Done."),
    ]

    with running_assistant_model(responses=responses) as (model_url, _model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Edit the recipe", "path": "dinners/pasta/recipe.md"},
            )

    # The tool has no path argument, so the update can only land on the
    # recipe being viewed; the soup is out of reach.
    assert status == 200
    assert body["edited"] is True
    assert soup.read_text(encoding="utf-8") == original_soup
    assert "Hacked." in pasta.read_text(encoding="utf-8")


def test_assistant_edit_on_index_is_not_offered(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "dinners" / "pasta" / "recipe.md"
    write_recipe(recipe, RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")
    original = recipe.read_text(encoding="utf-8")

    responses = [
        tool_call_response("update_current_recipe", {"content": "# Pasta\n\nHacked.\n"}),
        content_response("Edits are only available on a recipe page."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Edit the pasta recipe"},
            )

    assert status == 200
    assert body["edited"] is False
    assert recipe.read_text(encoding="utf-8") == original
    assert saved == []

    first_payload = model_state["payloads"][0]
    tool_names = [tool["function"]["name"] for tool in first_payload["tools"]]
    assert "update_current_recipe" not in tool_names

    # Even if the model hallucinates the tool call, the server refuses it.
    assert "only available on a recipe page" in model_state["payloads"][1]["messages"][-1]["content"]


def test_assistant_offer_has_no_delete_tool(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_assistant_model() as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            for path in (None, "dinners/pasta/recipe.md"):
                if path is not None:
                    write_recipe(source / "dinners" / "pasta" / "recipe.md", RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")
                payload = {"message": "hi", "path": path} if path else {"message": "hi"}
                request_json(f"{base_url}/api/ai-assistant", payload)

    for chat_payload in model_state["payloads"]:
        for tool in chat_payload["tools"]:
            assert "delete" not in tool["function"]["name"].lower()
            assert "bulk" not in tool["function"]["name"].lower()


def test_assistant_accepts_tool_arguments_as_json_string(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    pasta = source / "dinners" / "pasta" / "recipe.md"
    write_recipe(pasta, RECIPE_FRONT_MATTER, "# Pasta\n\n`2 tbsp` salt.\n")

    responses = [
        tool_call_response("update_current_recipe", json.dumps({"content": "# Pasta\n\n`1 tbsp` salt.\n"})),
        content_response("Done."),
    ]

    with running_assistant_model(responses=responses) as (model_url, _model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Halve the salt", "path": "dinners/pasta/recipe.md"},
            )

    assert status == 200
    assert body["edited"] is True
    assert "`1 tbsp` salt." in pasta.read_text(encoding="utf-8")


def test_assistant_reports_invalid_tool_arguments_to_the_model(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    pasta = source / "dinners" / "pasta" / "recipe.md"
    write_recipe(pasta, RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")

    responses = [
        tool_call_response("update_current_recipe", "this is not json"),
        content_response("That edit did not go through."),
    ]

    with running_assistant_model(responses=responses) as (model_url, model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(
                f"{base_url}/api/ai-assistant",
                {"message": "Halve the salt", "path": "dinners/pasta/recipe.md"},
            )

    assert status == 200
    assert body["edited"] is False
    assert "not valid JSON" in model_state["payloads"][1]["messages"][-1]["content"]


def test_assistant_streams_sse_events(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "dinners" / "pasta" / "recipe.md", RECIPE_FRONT_MATTER, "# Pasta\n\nBody.\n")

    with running_assistant_model() as (model_url, _model_state):
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            request = Request(
                f"{base_url}/api/ai-assistant",
                data=json.dumps({"message": "cups in a tablespoon?", "stream": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                assert response.headers["Content-Type"].startswith("text/event-stream")
                body = response.read().decode("utf-8")

    assert "event: status" in body
    assert "event: result" in body
    assert "There are 16 tablespoons in a cup." in body


def test_assistant_rejects_invalid_requests(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = config_for("http://127.0.0.1:1234/v1")

    with running_recipe_server(source, config=config) as (base_url, _saved, _deleted):
        for payload, expected in (
            ({"message": ""}, "non-empty message"),
            ({"message": "x" * 4001}, "too long"),
            ({"history": "not-a-list", "message": "hi"}, "history must be a list"),
            ({"message": "hi", "path": "../outside.md"}, "source directory"),
            ({"message": "hi", "path": "nope/recipe.txt"}, "Only Markdown"),
        ):
            status, body = request_json(f"{base_url}/api/ai-assistant", payload)
            assert status == 400
            assert expected in body["error"]

        # A missing recipe file answers 404.
        status, body = request_json(f"{base_url}/api/ai-assistant", {"message": "hi", "path": "nope/recipe.md"})
        assert status == 404


def test_assistant_is_unavailable_without_configuration(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = SimpleNamespace(
        model_endpoint="",
        all_purpose_model_name="",
        image_analysis_model="",
        new_recipe_prompt="",
        new_recipe_from_image_prompt="",
    )

    with running_recipe_server(source, config=config) as (base_url, _saved, _deleted):
        status, body = request_json(f"{base_url}/api/ai-assistant", {"message": "hi"})
        assert status == 503
        assert "not configured" in body["error"]


def test_assistant_reports_unavailable_model(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        unavailable_port = sock.getsockname()[1]

    config = config_for(f"http://127.0.0.1:{unavailable_port}/v1")

    with running_recipe_server(source, config=config) as (base_url, _saved, _deleted):
        status, body = request_json(f"{base_url}/api/ai-assistant", {"message": "hi"})
        assert status == 503
        assert "Could not reach" in body["error"]


def test_assistant_falls_back_when_the_model_lacks_tool_support(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    class NoToolsHandler(FakeAssistantModelHandler):
        state: dict = {}

        def do_POST(self):
            if self.path != "/api/chat":
                self._send_json(404, {"error": "Not found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            type(self).state.setdefault("payloads", []).append(payload)
            if payload.get("tools"):
                self._send_json(400, {"error": "this model does not support tools"})
                return
            self._send_json(200, content_response("There are 16 tablespoons in a cup."))

    server = ThreadingHTTPServer(("127.0.0.1", 0), NoToolsHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        model_url = f"http://127.0.0.1:{server.server_port}"
        with running_recipe_server(source, config=config_for(model_url)) as (base_url, _saved, _deleted):
            status, body = request_json(f"{base_url}/api/ai-assistant", {"message": "cups in a tablespoon?"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert status == 200
    assert body["reply"] == "There are 16 tablespoons in a cup."
    # The first request carried tools; the fallback did not.
    payloads = NoToolsHandler.state["payloads"]
    assert payloads[0]["tools"]
    assert "tools" not in payloads[1]
