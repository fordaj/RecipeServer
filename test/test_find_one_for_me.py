"""Tests for "Find One for Me" (issue #71).

Network and model calls are mocked: every web search goes through
``ai_recipe.search_image_candidates`` and every model call through
``ai_recipe._chat`` (or a real fake HTTP model server), and downloads
through ``ai_recipe.download_image`` / a local test server. No test uses
the live internet.
"""

from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
from io import BytesIO
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from recipeserver import ai_recipe
from recipeserver.ai_recipe import (
    ImageDownloadError,
    ImageSearchError,
    ModelUnavailable,
    download_image,
    find_image_for_recipe,
    parse_find_one_for_me_output,
    resolve_ai_config,
    search_image_candidates,
    substitute_recipe_title,
)
from recipeserver.server import RecipeRequestHandler

BASE = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"
RECIPE_SERVER_DIR = Path(__file__).parents[1] / "src" / "recipeserver"


def make_png_bytes(color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_BYTES = make_png_bytes()
PNG_DATA_URI = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"

CANDIDATES = [
    {
        "image_url": "https://example.com/images/brownies.jpg",
        "source_url": "https://example.com/recipes/brownies",
        "description": "Brownies on a plate",
        "attribution": "Example Cook",
    },
    {
        "image_url": "https://example.com/images/cake.png",
        "source_url": "https://example.com/recipes/cake",
        "description": "Chocolate cake",
        "attribution": "Example Baker",
    },
    {
        "image_url": "https://example.com/images/pie.webp",
        "source_url": "https://example.com/recipes/pie",
        "description": "Apple pie",
        "attribution": "",
    },
    {"image_url": "not a url", "source_url": None, "description": "Bogus", "attribution": None},
    {"image_url": "", "source_url": None, "description": "Missing", "attribution": None},
]


def make_config(**overrides):
    values = {
        "model_endpoint": "http://127.0.0.1:9999/v1",
        "all_purpose_model_name": "test-model",
        "image_analysis_model": "vision-model",
        "new_recipe_prompt": "Draft the recipe.",
        "new_recipe_from_image_prompt": "Transcribe.",
        "find_one_for_me_prompt": "Find an image for {{recipe_title}}.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def fake_download(image_url: str) -> dict:
    return {
        "filename": "found.png",
        "content_type": "image/png",
        "data_uri": PNG_DATA_URI,
        "byte_count": len(PNG_BYTES),
    }


# ---------------------------------------------------------------------------
# Prompt loading and substitution
# ---------------------------------------------------------------------------


def test_prompt_file_loads_externally_and_substitutes():
    prompt_path = RECIPE_SERVER_DIR / "FindOneForMePrompt.md"
    assert "{{search_query}}" in prompt_path.read_text(encoding="UTF-8")
    prompt = ai_recipe.load_find_one_for_me_prompt()
    assert "Find One for Me" in prompt

    assert ai_recipe.substitute_search_query(prompt, "chocolate brownies") is not None
    assert "chocolate brownies" in ai_recipe.substitute_search_query(prompt, "chocolate brownies")
    assert "{{search_query}}" not in ai_recipe.substitute_search_query(prompt, "chocolate brownies")
    # The legacy {{recipe_title}} placeholder is still substituted, and the
    # compatible alias keeps working for older prompt files.
    assert substitute_recipe_title("For {{recipe_title}}", "Soup") == "For Soup"
    assert substitute_recipe_title("For {{search_query}}", "Soup") == "For Soup"
    assert substitute_recipe_title("For {search_query}", "Soup") == "For Soup"


def test_config_resolves_find_image_prompt_from_disk_when_absent():
    config = SimpleNamespace(
        model_endpoint="http://localhost:11434/v1",
        all_purpose_model_name="m",
        image_analysis_model="",
        new_recipe_prompt="p",
        new_recipe_from_image_prompt="",
        # No find_one_for_me_prompt attribute at all.
    )
    resolved = resolve_ai_config(config)
    assert resolved.find_one_for_me_prompt
    assert resolved.is_find_image_configured is True


# ---------------------------------------------------------------------------
# Search mocking helpers
# ---------------------------------------------------------------------------


def stub_search(monkeypatch, candidates=None):
    calls: list[str] = []

    def fake_search(query: str, limit: int = 8):
        calls.append(query)
        return list(candidates if candidates is not None else CANDIDATES[:3])

    monkeypatch.setattr(ai_recipe, "search_image_candidates", fake_search)
    return calls


# ---------------------------------------------------------------------------
# find_image_for_recipe end-to-end (model + search + download mocked)
# ---------------------------------------------------------------------------


def test_find_image_uses_all_purpose_model_and_returns_candidate(monkeypatch):
    search_calls = stub_search(monkeypatch)
    chat_calls: list[dict] = []

    def fake_chat(endpoint, model_name, prompt, user_message, stage=""):
        chat_calls.append(
            {"endpoint": endpoint, "model": model_name, "prompt": prompt, "user": user_message, "stage": stage}
        )
        return json.dumps(
            {
                "image_url": "https://example.com/images/cake.png",
                "source_url": "https://example.com/recipes/cake",
                "description": "Chocolate cake",
                "attribution": "Example Baker",
            }
        )

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    result = find_image_for_recipe(make_config(), "Chocolate Cake")

    assert result["image_url"] == "https://example.com/images/cake.png"
    assert result["source_url"] == "https://example.com/recipes/cake"
    assert result["attribution"] == "Example Baker"
    assert result["filename"] == "found.png"
    assert result["data_uri"] == PNG_DATA_URI
    assert search_calls == ["Chocolate Cake"]
    # The all-purpose model (test-model), not the vision model, is used.
    assert chat_calls[0]["model"] == "test-model"
    assert chat_calls[0]["stage"] == "image selection"
    # The external prompt was used with the title substituted, and the user
    # message carries the real candidates (not invented URLs).
    assert "Chocolate Cake" in chat_calls[0]["prompt"]
    assert "Find an image" in chat_calls[0]["prompt"]
    assert "https://example.com/images/brownies.jpg" in chat_calls[0]["user"]


def test_repeated_calls_perform_fresh_searches(monkeypatch):
    search_calls = stub_search(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage=""):
        return json.dumps(
            {
                "image_url": "https://example.com/images/brownies.jpg",
                "source_url": None,
                "description": "Brownies",
                "attribution": None,
            }
        )

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    first = find_image_for_recipe(make_config(), "Brownies")
    second = find_image_for_recipe(make_config(), "Brownies")

    assert first["image_url"] == second["image_url"]
    # Every call searches again and calls the model again (no cached result).
    assert search_calls == ["Brownies", "Brownies"]


def test_candidate_order_is_shuffled_before_prompting(monkeypatch):
    seen_orders: list[list[str]] = []
    stub_search(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage=""):
        # Extract candidate order from the JSON block in the user message.
        start = user_message.index("[")
        end = user_message.rindex("]") + 1
        seen_orders.append([c["image_url"] for c in json.loads(user_message[start:end])])
        return json.dumps(
            {"image_url": seen_orders[-1][0], "source_url": None, "description": None, "attribution": None}
        )

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    for _ in range(12):
        find_image_for_recipe(make_config(), "Brownies")

    # Shuffling means the model does not always see the same order.
    assert len({tuple(order) for order in seen_orders}) > 1


def test_empty_title_rejected(monkeypatch):
    stub_search(monkeypatch)
    with pytest.raises(ImageSearchError):
        find_image_for_recipe(make_config(), "   ")


def test_not_configured_rejected():
    config = make_config(model_endpoint="", all_purpose_model_name="")
    # Patch prompt away so only the endpoint matters.
    config.find_one_for_me_prompt = ""
    with pytest.raises(ModelUnavailable):
        find_image_for_recipe(config, "Brownies")


def test_model_null_selection_maps_to_not_found(monkeypatch):
    stub_search(monkeypatch)
    monkeypatch.setattr(
        ai_recipe,
        "_chat",
        lambda *a, **k: json.dumps(
            {"image_url": None, "source_url": None, "description": None, "attribution": None}
        ),
    )
    with pytest.raises(ImageSearchError, match="No suitable image"):
        find_image_for_recipe(make_config(), "Brownies")


def test_model_fabricated_url_rejected(monkeypatch):
    stub_search(monkeypatch)
    monkeypatch.setattr(
        ai_recipe,
        "_chat",
        lambda *a, **k: json.dumps(
            {
                "image_url": "https://evil.example.com/fake.jpg",
                "source_url": None,
                "description": None,
                "attribution": None,
            }
        ),
    )
    with pytest.raises(ImageSearchError, match="not in the search results"):
        find_image_for_recipe(make_config(), "Brownies")


def test_search_failure_propagates_without_download(monkeypatch):
    def fake_search(query, limit=8):
        raise ImageSearchError("Image search failed: unreachable")

    monkeypatch.setattr(ai_recipe, "search_image_candidates", fake_search)
    downloads: list[str] = []
    monkeypatch.setattr(ai_recipe, "download_image", lambda url: downloads.append(url))
    with pytest.raises(ImageSearchError):
        find_image_for_recipe(make_config(), "Brownies")
    assert downloads == []


def test_download_failure_propagates(monkeypatch):
    stub_search(monkeypatch)
    monkeypatch.setattr(
        ai_recipe,
        "_chat",
        lambda *a, **k: json.dumps(
            {"image_url": "https://example.com/images/brownies.jpg", "source_url": None, "description": None, "attribution": None}
        ),
    )

    def bad_download(url):
        raise ImageDownloadError("Failed to download the selected image: 404")

    monkeypatch.setattr(ai_recipe, "download_image", bad_download)
    with pytest.raises(ImageDownloadError, match="Failed to download"):
        find_image_for_recipe(make_config(), "Brownies")


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_parse_find_one_for_me_output_handles_fences_and_nulls():
    fenced = '```json\n{"image_url": "https://x.example.com/a.jpg"}\n```'
    assert parse_find_one_for_me_output(fenced)["image_url"] == "https://x.example.com/a.jpg"
    assert parse_find_one_for_me_output('{"image_url": null}') is None
    with pytest.raises(ImageSearchError):
        parse_find_one_for_me_output("not json")
    with pytest.raises(ImageSearchError):
        parse_find_one_for_me_output('{"image_url": "ftp://x/a.jpg"}')


def test_search_rejects_empty_query():
    with pytest.raises(ImageSearchError):
        search_image_candidates("   ")


def test_download_rejects_invalid_urls_and_missing_hosts():
    with pytest.raises(ImageDownloadError):
        download_image("not-a-url")
    with pytest.raises(ImageDownloadError):
        download_image("")


class _FakeResponse:
    """Minimal urlopen response mock: headers, read(), context manager."""

    def __init__(self, body: bytes, content_type: str):
        self._body = body
        self.headers = self
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type

    def get(self, name, default=None):
        return self._content_type if name.lower() == "content-type" else default

    def read(self, limit=None):
        return self._body if limit is None else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_download_image_validates_png_and_builds_data_uri(monkeypatch):
    monkeypatch.setattr(
        ai_recipe, "urlopen", lambda req, timeout=None: _FakeResponse(PNG_BYTES, "image/png")
    )
    result = download_image("https://cdn.example.com/photos/dish.png?x=1")
    assert result["filename"] == "dish.png"
    assert result["content_type"] == "image/png"
    assert result["data_uri"] == PNG_DATA_URI
    assert result["byte_count"] == len(PNG_BYTES)


def test_download_image_rejects_non_image_bytes(monkeypatch):
    monkeypatch.setattr(
        ai_recipe, "urlopen", lambda req, timeout=None: _FakeResponse(b"<html>nope</html>", "text/html")
    )
    with pytest.raises(ImageDownloadError):
        download_image("https://cdn.example.com/page.html")


def test_download_image_rejects_oversized(monkeypatch):
    big = b"x" * (ai_recipe.MAX_DOWNLOAD_IMAGE_BYTES + 1)
    monkeypatch.setattr(
        ai_recipe, "urlopen", lambda req, timeout=None: _FakeResponse(big, "image/png")
    )
    with pytest.raises(ImageDownloadError, match="too large"):
        download_image("https://cdn.example.com/big.png")


def test_filename_derivation_falls_back_to_content_type():
    filename, mime = ai_recipe._filename_for_download("https://cdn.example.com/download?id=1", "image/webp")
    assert filename.endswith(".webp")
    assert mime == "image/webp"


# ---------------------------------------------------------------------------
# HTTP API via /api/find-image
# ---------------------------------------------------------------------------


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


def test_find_image_api_success_and_repeat_clicks(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config = make_config()

    picks = iter(
        [
            "https://example.com/images/brownies.jpg",
            "https://example.com/images/cake.png",
        ]
    )

    def fake_search(query, limit=8):
        return list(CANDIDATES[:3])

    monkeypatch.setattr(ai_recipe, "search_image_candidates", fake_search)
    monkeypatch.setattr(
        ai_recipe,
        "_chat",
        lambda *a, **k: json.dumps(
            {"image_url": next(picks), "source_url": None, "description": None, "attribution": None}
        ),
    )
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/find-image", {"query": "Brownies"})
        assert status == 200
        assert body["image_url"].endswith("brownies.jpg")
        assert body["data_uri"] == PNG_DATA_URI

        # A second click performs a fresh search and may return a new image.
        status, body = request_json(f"{base_url}/api/find-image", {"query": "Brownies"})
        assert status == 200
        assert body["image_url"].endswith("cake.png")


def test_find_image_api_empty_query_and_not_found(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config = make_config()

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/find-image", {"query": "   "})
        assert status == 400
        assert "search query" in body["error"]

    monkeypatch.setattr(
        ai_recipe,
        "search_image_candidates",
        lambda query, limit=8: (_ for _ in ()).throw(ImageSearchError(f"No suitable image found for {query!r}")),
    )
    monkeypatch.setattr(ai_recipe, "_chat", lambda *a, **k: "{}")
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/find-image", {"query": "Nothing"})
        assert status == 404
        assert "No suitable image" in body["error"]


def test_find_image_api_download_failure(tmp_path, monkeypatch):
    source = tmp_path / "recipes"
    source.mkdir()
    config = make_config()
    monkeypatch.setattr(ai_recipe, "search_image_candidates", lambda query, limit=8: list(CANDIDATES[:1]))
    monkeypatch.setattr(
        ai_recipe,
        "_chat",
        lambda *a, **k: json.dumps(
            {"image_url": CANDIDATES[0]["image_url"], "source_url": None, "description": None, "attribution": None}
        ),
    )

    def bad_download(url):
        raise ImageDownloadError("Failed to download the selected image: 404 Not Found")

    monkeypatch.setattr(ai_recipe, "download_image", bad_download)
    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/find-image", {"query": "Brownies"})
        assert status == 502
        assert "Failed to download" in body["error"]


def test_find_image_api_searches_the_typed_query_not_a_title(tmp_path, monkeypatch):
    """The typed query is what reaches search/model, not a Markdown heading."""
    source = tmp_path / "recipes"
    source.mkdir()
    config = make_config(find_one_for_me_prompt="Search for {{search_query}}.")
    seen_queries: list[str] = []

    def fake_search(query, limit=8):
        seen_queries.append(query)
        return list(CANDIDATES[:1])

    monkeypatch.setattr(ai_recipe, "search_image_candidates", fake_search)

    def record_chat(endpoint, model_name, prompt, user_message, stage=""):
        seen_queries.append(prompt)
        return json.dumps(
            {"image_url": CANDIDATES[0]["image_url"], "source_url": None, "description": None, "attribution": None}
        )

    monkeypatch.setattr(ai_recipe, "_chat", record_chat)
    monkeypatch.setattr(ai_recipe, "download_image", fake_download)

    with running_recipe_server(source, config) as base_url:
        status, body = request_json(
            f"{base_url}/api/find-image", {"query": "grandma's chocolate brownies"}
        )
        assert status == 200

    assert seen_queries[0] == "grandma's chocolate brownies"
    assert "grandma's chocolate brownies" in seen_queries[1]


def test_find_image_api_disabled_without_endpoint(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    config = make_config(model_endpoint="", find_one_for_me_prompt="")
    with running_recipe_server(source, config) as base_url:
        status, body = request_json(f"{base_url}/api/find-image", {"query": "Brownies"})
        assert status == 503
        assert "not configured" in body["error"]


# ---------------------------------------------------------------------------
# UI contract (static assets)
# ---------------------------------------------------------------------------


def test_ui_has_find_image_button_with_ai_icon_alongside_image_input():
    markup = (BASE / "files.html").read_text(encoding="UTF-8")
    css = (BASE / "recipe-editor.css").read_text(encoding="UTF-8")
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")

    # The existing image input is still there, and the new button sits
    # alongside a user-typed search query in the same images panel.
    assert 'id="recipe-editor-images"' in markup
    assert 'id="recipe-editor-find-image"' in markup
    assert 'id="recipe-editor-find-image-query"' in markup
    assert 'class="recipe-editor__find-image"' in markup
    assert 'aria-label="Find an image for me"' in markup
    assert 'title="Find an image for me"' in markup
    assert "/assets/ai.svg" in markup
    assert 'class="recipe-editor__images-preview"' in markup
    # The find-image controls live outside the dropzone so clicks on the
    # query/buttons can't fall through and open the file picker.
    images_section = markup.split('class="recipe-editor__images"')[1].split("</div>")[0]
    assert 'id="recipe-editor-images"' in images_section
    assert 'id="recipe-editor-find-image"' not in images_section
    assert 'id="recipe-editor-find-image-query"' not in images_section

    # The copy-image-name button uses copy.svg and sits next to the name.
    assert 'id="recipe-editor-copy-image-name"' in markup
    assert 'src="/assets/copy.svg"' in markup
    assert 'aria-label="Copy image name"' in markup
    assert "recipe-editor__images-selected-row" in markup

    # Save-button styling: filled food-color background, same hover color,
    # and an accessible focus state.
    assert ".recipe-editor__find-image" in css
    find_block = css.split(".recipe-editor__find-image {")[1].split("}")[0]
    assert "background: var(--food-color)" in find_block
    assert "color: var(--page-bg)" in find_block
    assert ".recipe-editor__find-image:hover:not(:disabled)" in css
    assert "var(--food-color-hover)" in css
    assert ".recipe-editor__find-image:focus-visible" in css

    # Frontend behaviour: busy guard, loading status, empty-query handling,
    # fresh POST per click, and preservation of the existing image on error.
    # The search text is typed by the user, never parsed from Markdown.
    assert "extractRecipeTitle" not in script
    assert "findImageQuery" in script
    assert "Type a search query before searching" in script
    assert "findImageBusy" in script
    assert "Searching for an image" in script
    assert 'method: "POST"' in script
    assert "FIND_IMAGE_API" in script
    assert "JSON.stringify({ query })" in script
    # Enter in the query box searches instead of submitting the dialog form.
    assert 'findImageQuery.addEventListener("keydown"' in script
    # Input is only replaced after a successful response, never on error.
    assert "refs.imageInput.files = transfer.files" in script
    error_block = script.split("No image found")[0].split("catch (error)")[-1]
    assert "refs.imageInput.files" not in error_block
    assert "dataUriToFile" in script
    assert "imagePreview" in script
    # Clicking the button must not trigger the dropzone's file picker.
    assert 'event.target.closest("button")' in script
    # Copy-to-clipboard uses the clipboard API with the selected filename
    # and surfaces the result as a tooltip/status.
    assert "navigator.clipboard" in script
    assert "clipboard.writeText" in script
    assert "navigator.clipboard?.writeText" in script
    assert "copyImageNameButton" in script
    assert "Copied image name" in script


def test_ui_button_is_wired_and_enabled_from_ai_status():
    script = (BASE / "recipe-editor.js").read_text(encoding="UTF-8")
    assert "setFindImageState" in script
    assert "find_image_available" in script
    assert 'refs.findImageButton.addEventListener("click"' in script
    assert "ai.findImageForMe" in script
    # The button stays clickable again after a finished request.
    finally_block = script.split("findImageBusy = false")[-1]
    assert "findImageButton.disabled" in finally_block
