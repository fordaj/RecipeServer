"""Tests for the "Find One For Me" feature.

External web searches and model responses are mocked throughout; no test
requires live internet access.
"""

from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import base64
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from PIL import Image

import recipeserver.ai_recipe as ai_recipe
import recipeserver.image_download as image_download
import recipeserver.image_search as image_search
from recipeserver.ai_recipe import (
    ImageDownloadError,
    ImageSearchError,
    ModelRequestError,
    ModelUnavailable,
    find_recipe_image,
)
from recipeserver.config import Configuration
from recipeserver.server import RecipeRequestHandler
from recipeserver.image_search import ImageCandidate as SearchCandidate

EDITOR_ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"


def png_image(size=(8, 8), color="red"):
    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return output.getvalue()


def make_candidates():
    return [
        SearchCandidate(
            url=f"https://images.example.com/{name}.jpg",
            source_url=f"https://sources.example.com/{name}",
            title=f"Photo of {name}",
            attribution=f"Author {name}",
            license="by",
            width=1024,
            height=768,
        )
        for name in ("one", "two", "three")
    ]


def make_config(**overrides):
    config = {
        "model_endpoint": "http://localhost:11434",
        "all_purpose_model_name": "all-purpose-model",
        "image_analysis_model": "vision-model",
        "new_recipe_prompt": "Draft the recipe.",
        "new_recipe_from_image_prompt": "Transcribe the recipe image.",
        "find_one_for_me_prompt": "Pick an image for {{recipe_title}}. Only use real search results.",
    }
    config.update(overrides)
    return SimpleNamespace(**config)


def downloaded_image():
    return image_download.DownloadedImage(content=png_image(), extension=".jpg", mime_type="image/jpeg")


@contextmanager
def capture_model_call():
    calls = []

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        calls.append(
            {
                "endpoint": endpoint,
                "model_name": model_name,
                "prompt": prompt,
                "user_message": user_message,
                "stage": stage,
                "images": images,
            }
        )
        return json.dumps({"image_url": "https://images.example.com/two.jpg", "description": "A photo", "attribution": "Author two"})

    original = ai_recipe._chat
    ai_recipe._chat = fake_chat
    try:
        yield calls
    finally:
        ai_recipe._chat = original


def patch_search_and_download(monkeypatch, candidates=None, downloaded=None):
    state = {"searches": [], "downloads": []}
    monkeypatch.setattr(
        ai_recipe,
        "search_images",
        lambda query, *args, **kwargs: state["searches"].append(query) or list(candidates or make_candidates()),
    )

    def fake_download(url, *args, **kwargs):
        state["downloads"].append(url)
        return downloaded or downloaded_image()

    monkeypatch.setattr(ai_recipe, "download_image", fake_download)
    return state


# ----- Prompt loading and substitution ----- #


def test_find_one_for_me_prompt_is_loaded_from_the_external_file():
    config = Configuration()
    prompt = config.load_find_one_for_me_prompt()

    assert "{{recipe_title}}" in prompt
    assert config.find_one_for_me_prompt == prompt
    assert (Path(ai_recipe.__file__).parent / "FindOneForMePrompt.md").read_text(encoding="utf-8").strip() == prompt


def test_find_recipe_image_substitutes_the_recipe_title_into_the_prompt(monkeypatch):
    state = patch_search_and_download(monkeypatch)
    with capture_model_call() as calls:
        find_recipe_image(make_config(), "Chicken Soup")

    prompt = calls[0]["prompt"]
    assert "Chicken Soup" in prompt
    assert "{{recipe_title}}" not in prompt
    assert state["searches"] == ["Chicken Soup"]


def test_find_recipe_image_keeps_the_all_purpose_model_and_ignores_the_image_model(monkeypatch):
    patch_search_and_download(monkeypatch)
    with capture_model_call() as calls:
        find_recipe_image(make_config(), "Chicken Soup")

    assert calls[0]["model_name"] == "all-purpose-model"
    assert calls[0]["model_name"] != "vision-model"


def test_find_recipe_image_requires_a_configured_model(monkeypatch):
    patch_search_and_download(monkeypatch)
    with pytest.raises(ModelUnavailable):
        find_recipe_image(make_config(model_endpoint=""), "Chicken Soup")


def test_find_recipe_image_requires_the_prompt_file(monkeypatch):
    patch_search_and_download(monkeypatch)
    with pytest.raises(ModelUnavailable):
        find_recipe_image(make_config(find_one_for_me_prompt=""), "Chicken Soup")


def test_find_recipe_image_auto_detects_the_model_when_none_is_configured(monkeypatch):
    patch_search_and_download(monkeypatch)
    monkeypatch.setattr(ai_recipe, "list_models", lambda endpoint, timeout=None: ["auto-model:latest"])
    with capture_model_call() as calls:
        find_recipe_image(make_config(all_purpose_model_name=""), "Chicken Soup")

    assert calls[0]["model_name"] == "auto-model:latest"


def test_find_recipe_image_fails_when_no_model_can_be_resolved(monkeypatch):
    patch_search_and_download(monkeypatch)
    monkeypatch.setattr(ai_recipe, "list_models", lambda endpoint, timeout=None: [])
    with pytest.raises(ModelUnavailable):
        find_recipe_image(make_config(all_purpose_model_name=""), "Chicken Soup")


def test_find_recipe_image_rejects_an_empty_or_missing_query(monkeypatch):
    patch_search_and_download(monkeypatch)
    with pytest.raises(ValueError):
        find_recipe_image(make_config(), "")
    with pytest.raises(ValueError):
        find_recipe_image(make_config(), "   ")
    with pytest.raises(ValueError):
        find_recipe_image(make_config(), None)


# ----- Search result handling and random selection ----- #


def test_candidates_are_shuffled_before_the_model_sees_them(monkeypatch):
    state = patch_search_and_download(monkeypatch)
    monkeypatch.setattr(ai_recipe.random, "shuffle", lambda items: items.reverse())
    with capture_model_call() as calls:
        find_recipe_image(make_config(), "Chicken Soup")

    message = calls[0]["user_message"]
    first_listed = message.index("https://images.example.com/three.jpg")
    last_listed = message.index("https://images.example.com/one.jpg")
    assert first_listed < last_listed
    assert "https://images.example.com/two.jpg" in message


def test_the_model_pick_is_downloaded_and_returned(monkeypatch):
    state = patch_search_and_download(monkeypatch)
    with capture_model_call():
        result = find_recipe_image(make_config(), "Chicken Soup")

    assert state["downloads"] == ["https://images.example.com/two.jpg"]
    assert result["data_base64"]
    decoded = base64.b64decode(result["data_base64"])
    assert decoded.startswith(b"\x89PNG")
    assert result["mime_type"] == "image/jpeg"
    assert result["filename"] == "chicken-soup.jpg"
    # Source information is preserved from the model response when present.
    assert result["source_url"] == "https://sources.example.com/two"
    assert result["attribution"] == "Author two"
    assert result["description"] == "A photo"


def test_missing_source_details_fall_back_to_the_search_provider(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return '{"image_url": "https://images.example.com/three.jpg"}'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    result = find_recipe_image(make_config(), "Chicken Soup")

    assert result["source_url"] == "https://sources.example.com/three"
    assert result["attribution"] == "Author three"
    assert result["description"] == "Photo of three"


def test_model_output_wrapped_in_a_code_fence_is_parsed(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return '```json\n{"image_url": "https://images.example.com/one.jpg"}\n```'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    result = find_recipe_image(make_config(), "Chicken Soup")

    assert result["filename"] == "chicken-soup.jpg"


def test_model_output_with_surrounding_text_is_parsed(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return 'I pick this one:\n{"image_url": "https://images.example.com/one.jpg", "description": "ok"}\nDone.'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    result = find_recipe_image(make_config(), "Chicken Soup")

    assert result["description"] == "ok"


def test_repeated_clicks_each_perform_a_fresh_search_and_model_call(monkeypatch):
    state = patch_search_and_download(monkeypatch)
    with capture_model_call() as calls:
        find_recipe_image(make_config(), "Chicken Soup")
        find_recipe_image(make_config(), "Chicken Soup")

    assert state["searches"] == ["Chicken Soup", "Chicken Soup"]
    assert len(calls) == 2
    assert len(state["downloads"]) == 2


# ----- Invalid or missing image URLs ----- #


def test_model_returning_null_means_no_suitable_image(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return '{"image_url": null, "source_url": null, "description": null, "attribution": null}'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    with pytest.raises(ImageSearchError, match="[Nn]o suitable image"):
        find_recipe_image(make_config(), "Chicken Soup")


def test_model_returning_an_unknown_url_is_rejected(monkeypatch):
    downloads = []
    monkeypatch.setattr(ai_recipe, "search_images", lambda *a, **k: make_candidates())
    monkeypatch.setattr(ai_recipe, "download_image", lambda url, *a, **k: downloads.append(url) or downloaded_image())

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return '{"image_url": "https://evil.example.com/steal.png"}'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    with pytest.raises(ModelRequestError):
        find_recipe_image(make_config(), "Chicken Soup")
    assert downloads == []


def test_model_returning_garbage_is_rejected(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return "I cannot help with that."

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    with pytest.raises(ModelRequestError):
        find_recipe_image(make_config(), "Chicken Soup")


def test_model_returning_an_empty_url_is_rejected(monkeypatch):
    patch_search_and_download(monkeypatch)

    def fake_chat(endpoint, model_name, prompt, user_message, stage="recipe generation", images=None):
        return '{"image_url": "   "}'

    monkeypatch.setattr(ai_recipe, "_chat", fake_chat)
    with pytest.raises(ModelRequestError):
        find_recipe_image(make_config(), "Chicken Soup")


# ----- Failed searches and failed downloads ----- #


def test_a_failed_search_propagates_and_downloads_nothing(monkeypatch):
    downloads = []
    monkeypatch.setattr(
        ai_recipe,
        "search_images",
        lambda *a, **k: (_ for _ in ()).throw(ImageSearchError("search is down")),
    )
    monkeypatch.setattr(ai_recipe, "download_image", lambda url, *a, **k: downloads.append(url) or downloaded_image())

    with pytest.raises(ImageSearchError, match="search is down"):
        find_recipe_image(make_config(), "Chicken Soup")
    assert downloads == []


def test_a_failed_download_propagates(monkeypatch):
    monkeypatch.setattr(ai_recipe, "search_images", lambda *a, **k: make_candidates())
    attempts = []

    def fake_download(url, *args, **kwargs):
        attempts.append(url)
        raise ImageDownloadError("unable to download the image: connection reset")

    monkeypatch.setattr(ai_recipe, "download_image", fake_download)
    with capture_model_call():
        with pytest.raises(ImageDownloadError, match="candidate images"):
            find_recipe_image(make_config(), "Chicken Soup")

    # The model's pick is tried first, then alternative search results.
    assert len(attempts) == len(make_candidates())
    assert attempts[0] == "https://images.example.com/two.jpg"


def test_a_failed_download_falls_back_to_the_next_candidate(monkeypatch):
    monkeypatch.setattr(ai_recipe, "search_images", lambda *a, **k: make_candidates())
    attempts = []

    def fake_download(url, *args, **kwargs):
        attempts.append(url)
        if url == "https://images.example.com/two.jpg":
            raise ImageDownloadError("The image host returned HTTP 429")
        return downloaded_image()

    monkeypatch.setattr(ai_recipe, "download_image", fake_download)
    with capture_model_call():
        result = find_recipe_image(make_config(), "Chicken Soup")

    assert attempts[0] == "https://images.example.com/two.jpg"
    # The next candidate in shuffled order is used; its own metadata wins.
    assert len(attempts) == 2
    assert result["source_url"] in {"https://sources.example.com/one", "https://sources.example.com/three"}


def test_download_fallback_is_capped(monkeypatch):
    candidates = make_candidates() * 4  # 12 candidates; the cap is what matters
    monkeypatch.setattr(ai_recipe, "search_images", lambda *a, **k: list(candidates))
    attempts = []

    def fake_download(url, *args, **kwargs):
        attempts.append(url)
        raise ImageDownloadError("nope")

    monkeypatch.setattr(ai_recipe, "download_image", fake_download)
    with capture_model_call():
        with pytest.raises(ImageDownloadError, match="4 candidate images"):
            find_recipe_image(make_config(), "Chicken Soup")

    assert len(attempts) == ai_recipe.MAX_DOWNLOAD_ATTEMPTS


# ----- The search provider itself ----- #


class _FakeSearchResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self, limit):
        return self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def commons_page(
    title, *, url, thumburl=None, width=4000, height=3000, thumbwidth=1024, thumbheight=768, artist=None, license_name="CC BY 2.0", index=1
):
    info = {
        "url": url + "?utm_source=commons.wikimedia.org&utm_content=1",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
        "width": width,
        "height": height,
        "extmetadata": {},
    }
    if thumburl is not None:
        info["thumburl"] = thumburl + "?utm_source=commons.wikimedia.org&utm_content=1"
        info["thumbwidth"] = thumbwidth
        info["thumbheight"] = thumbheight
    if artist is not None:
        info["extmetadata"]["Artist"] = {"value": f'<a rel="nofollow" href="https://example.com">{artist}</a>'}
        info["extmetadata"]["LicenseShortName"] = {"value": license_name}
    return {"title": title, "index": index, "imageinfo": [info]}


def test_search_images_parses_and_filters_candidates(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "1": commons_page(
                    "File:Good teriyaki.jpg",
                    url="https://upload.wikimedia.org/wikipedia/commons/g/good.jpg",
                    thumburl="https://thumb.wikimedia.org/wikipedia/commons/thumb/g/good.jpg/1024px-good.jpg",
                    artist="Alice",
                    license_name="CC BY 2.0",
                    index=1,
                ),
                "2": commons_page(
                    "File:Icon.svg",  # SVG is rejected
                    url="https://upload.wikimedia.org/wikipedia/commons/i/icon.svg",
                    index=2,
                ),
                "3": commons_page(
                    "File:Tiny.jpg",  # too small
                    url="https://upload.wikimedia.org/wikipedia/commons/t/tiny.jpg",
                    width=100,
                    height=80,
                    index=3,
                ),
                "4": commons_page(
                    "File:Guide.pdf",  # not a raster image
                    url="https://upload.wikimedia.org/wikipedia/commons/g/guide.pdf",
                    index=4,
                ),
            }
        }
    }
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    candidates = image_search.search_images("teriyaki sauce")

    assert [candidate.url for candidate in candidates] == ["https://thumb.wikimedia.org/wikipedia/commons/thumb/g/good.jpg/1024px-good.jpg"]
    assert candidates[0].attribution == "Alice (CC BY 2.0)"
    assert candidates[0].license == "CC BY 2.0"
    assert candidates[0].source_url == "https://commons.wikimedia.org/wiki/File:Good_teriyaki.jpg"
    assert candidates[0].title == "Good teriyaki.jpg"
    assert candidates[0].width == 1024
    assert candidates[0].height == 768


def test_search_images_falls_back_to_the_original_url_when_no_thumb(monkeypatch):
    payload = {"query": {"pages": {"1": commons_page("File:Full.jpg", url="https://upload.wikimedia.org/wikipedia/commons/f/full.jpg", index=1)}}}
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    candidates = image_search.search_images("teriyaki")

    assert candidates[0].url == "https://upload.wikimedia.org/wikipedia/commons/f/full.jpg"


def test_search_images_orders_candidates_by_search_rank(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "a": commons_page("File:Second.jpg", url="https://upload.wikimedia.org/wikipedia/commons/s/second.jpg", index=2),
                "b": commons_page("File:First.jpg", url="https://upload.wikimedia.org/wikipedia/commons/f/first.jpg", index=1),
            }
        }
    }
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    candidates = image_search.search_images("teriyaki")

    assert [candidate.url for candidate in candidates] == [
        "https://upload.wikimedia.org/wikipedia/commons/f/first.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/s/second.jpg",
    ]


def test_search_images_raises_when_nothing_usable_is_found(monkeypatch):
    payload = {"query": {"pages": {"1": commons_page("File:Icon.svg", url="https://upload.wikimedia.org/wikipedia/commons/i/icon.svg", index=1)}}}
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    with pytest.raises(ImageSearchError, match="[Nn]o suitable images"):
        image_search.search_images("teriyaki")


def test_search_images_raises_on_http_errors(monkeypatch):
    def fake_urlopen(request, timeout=10):
        raise HTTPError("https://commons.wikimedia.org", 503, "unavailable", hdrs=None, fp=None)

    monkeypatch.setattr(image_search, "urlopen", fake_urlopen)
    with pytest.raises(ImageSearchError, match="503"):
        image_search.search_images("teriyaki")


def test_search_images_raises_on_invalid_json(monkeypatch):
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(b"not json"))

    with pytest.raises(ImageSearchError, match="invalid response"):
        image_search.search_images("teriyaki")


def test_search_images_requires_a_query():
    with pytest.raises(ImageSearchError):
        image_search.search_images("   ")


# ----- Image downloading ----- #


class _LocalImageHandler(BaseHTTPRequestHandler):
    body = b""
    content_type = "image/png"
    status = 200

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.end_headers()
            return
        self.send_response(self.status)
        self.send_header("Content-Type", self.content_type)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)


@contextmanager
def local_image_server(body, content_type="image/png", status=200):
    handler = type("Handler", (_LocalImageHandler,), {"body": body, "content_type": content_type, "status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_download_image_downloads_and_verifies_png(monkeypatch):
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    body = png_image()
    with local_image_server(body, "image/png") as base_url:
        result = image_download.download_image(f"{base_url}/image.png")

    assert result.content == body
    assert result.extension == ".png"
    assert result.mime_type == "image/png"


def test_download_image_rejects_non_image_content(monkeypatch):
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    with local_image_server(b"<html>nope</html>", "text/html") as base_url:
        with pytest.raises(ImageDownloadError):
            image_download.download_image(f"{base_url}/page.html")


def test_download_image_rejects_svg(monkeypatch):
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    with local_image_server(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml") as base_url:
        with pytest.raises(ImageDownloadError, match="SVG"):
            image_download.download_image(f"{base_url}/icon.svg")


def test_download_image_rejects_invalid_image_bytes(monkeypatch):
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    with local_image_server(b"this is not a real image", "image/png") as base_url:
        with pytest.raises(ImageDownloadError, match="not a valid image"):
            image_download.download_image(f"{base_url}/fake.png")


def test_download_image_enforces_the_size_limit(monkeypatch):
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    with local_image_server(b"x" * 4096, "image/png") as base_url:
        with pytest.raises(ImageDownloadError, match="too large"):
            image_download.download_image(f"{base_url}/big.png", max_bytes=1024)


def test_validate_external_url_rejects_non_public_addresses():
    # Literal loopback, link-local, and metadata IPs are rejected outright.
    for url in (
        "http://127.0.0.1/image.png",
        "http://[::1]/image.png",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/image.png",
    ):
        with pytest.raises(ImageDownloadError):
            image_download.validate_external_url(url)

    assert image_download.validate_external_url("https://93.184.216.34/image.png") == "https://93.184.216.34/image.png"


def test_validate_external_url_rejects_a_host_that_resolves_to_a_private_address(monkeypatch):
    monkeypatch.setattr(image_download, "_resolve_addresses", lambda hostname: ["192.168.1.20"])

    with pytest.raises(ImageDownloadError):
        image_download.validate_external_url("https://images.example.com/image.png")


def test_validate_external_url_rejects_non_http_schemes():
    with pytest.raises(ImageDownloadError):
        image_download.validate_external_url("ftp://images.example.com/image.png")
    with pytest.raises(ImageDownloadError):
        image_download.validate_external_url("file:///etc/passwd")


def test_download_image_blocks_redirects_to_private_addresses(monkeypatch):
    # The initial host resolves publicly, but the redirect target resolves to
    # the cloud metadata service; the redirect handler must refuse to follow it.
    mapping = {"127.0.0.1": ["93.184.216.34"], "169.254.169.254": ["169.254.169.254"]}
    monkeypatch.setattr(image_download, "_resolve_addresses", lambda hostname: mapping.get(hostname, ["93.184.216.34"]))

    with local_image_server(b"", "image/png") as base_url:
        with pytest.raises(ImageDownloadError):
            image_download.download_image(f"{base_url}/redirect")


def test_find_recipe_image_leaves_the_selection_untouched_on_failure(monkeypatch):
    """A failed search must not return an image; the caller keeps the old one."""
    monkeypatch.setattr(
        ai_recipe,
        "search_images",
        lambda *a, **k: (_ for _ in ()).throw(ImageSearchError("no results")),
    )
    with pytest.raises(ImageSearchError):
        find_recipe_image(make_config(), "Chicken Soup")


# ----- The HTTP endpoint ----- #


@pytest.fixture
def api_server(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    handler = partial(RecipeRequestHandler, directory=str(tmp_path), source_directory=source)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def post_find_image(base_url, payload):
    request = Request(
        f"{base_url}/api/find-image",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urlopen(request)


def test_find_image_endpoint_returns_the_image(api_server, monkeypatch):
    monkeypatch.setattr(
        ai_recipe,
        "find_recipe_image",
        lambda config, query: {
            "filename": "chicken-soup.jpg",
            "mime_type": "image/jpeg",
            "data_base64": base64.b64encode(png_image()).decode("ascii"),
            "source_url": "https://sources.example.com/two",
            "attribution": "Author two",
            "description": "A photo",
            "width": 800,
            "height": 600,
        },
    )

    with post_find_image(api_server, {"query": "Chicken Soup"}) as response:
        body = json.loads(response.read())

    assert response.status == 200
    assert body["filename"] == "chicken-soup.jpg"
    assert body["source_url"] == "https://sources.example.com/two"
    assert body["attribution"] == "Author two"


def test_find_image_endpoint_rejects_an_empty_query(api_server):
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {"query": "   "})
    assert excinfo.value.code == 400


def test_find_image_endpoint_rejects_an_oversized_query(api_server):
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {"query": "x" * (ai_recipe.MAX_QUERY_CHARS + 1)})
    assert excinfo.value.code == 400


def test_find_image_endpoint_rejects_a_missing_query(api_server):
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {})
    assert excinfo.value.code == 400


def test_find_image_endpoint_reports_model_unavailable(api_server, monkeypatch):
    monkeypatch.setattr(
        ai_recipe,
        "find_recipe_image",
        lambda config, query: (_ for _ in ()).throw(ModelUnavailable("The local model is not configured")),
    )
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {"query": "Chicken Soup"})
    assert excinfo.value.code == 503


def test_find_image_endpoint_reports_search_failures(api_server, monkeypatch):
    monkeypatch.setattr(
        ai_recipe,
        "find_recipe_image",
        lambda config, query: (_ for _ in ()).throw(ImageSearchError("No suitable images were found")),
    )
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {"query": "Chicken Soup"})
    assert excinfo.value.code == 502


def test_find_image_endpoint_reports_download_failures(api_server, monkeypatch):
    monkeypatch.setattr(
        ai_recipe,
        "find_recipe_image",
        lambda config, query: (_ for _ in ()).throw(ImageDownloadError("Unable to download the image")),
    )
    with pytest.raises(HTTPError) as excinfo:
        post_find_image(api_server, {"query": "Chicken Soup"})
    assert excinfo.value.code == 502


# ----- The browser UI ----- #


def test_find_image_button_markup_and_accessibility():
    markup = (EDITOR_ASSETS / "files.html").read_text(encoding="utf-8")

    assert 'class="recipe-editor__find-image"' in markup
    assert 'aria-label="Find One For Me"' in markup
    assert 'title="Find One For Me"' in markup
    assert 'class="recipe-editor__find-image-icon"' in markup
    assert "ai.svg" not in markup  # inlined at runtime via RecipeIcons, never embedded


def test_find_image_button_matches_the_save_button_styling():
    css = (EDITOR_ASSETS / "recipe-editor.css").read_text(encoding="utf-8")
    find = css.split(".recipe-editor__find-image {")[1].split("}")[0]

    # Same border, fill, text colour, radius, padding, and type as Save.
    for declaration in (
        "border: 1px solid var(--food-color);",
        "background: var(--food-color);",
        "color: var(--page-bg);",
        "border-radius: 6px;",
        "padding: 0.65rem 1rem;",
        "font-size: 0.9rem;",
    ):
        assert declaration in find

    hover = css.split(".recipe-editor__find-image:hover:not(:disabled) {")[1].split("}")[0]
    assert "var(--food-color-hover)" in hover
    assert ".recipe-editor__find-image:focus-visible" in css
    assert ".recipe-editor__find-image:disabled" in css


def test_find_image_button_is_wired_into_the_editor_script():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert 'const FIND_IMAGE_API = "/api/find-image";' in script
    assert 'const AI_ICON_URL = "/assets/ai.svg";' in script
    assert 'findImageButton: dialog.querySelector(".recipe-editor__find-image")' in script
    assert 'refs.findImageButton.addEventListener("click", ctx.findImage.findImage)' in script
    # The button is inlined with the shared icon helper so currentColor works.
    assert "RecipeIcons.loadSvgIcon(AI_ICON_URL)" in script
    # Repeated clicks must not overlap requests: a local guard plus disabling.
    assert "state.findImageBusy" in script
    assert 'setAttribute("aria-busy"' in script
    assert '"Searching…"' in script


def test_find_image_failure_preserves_the_existing_image():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")
    find_image = script.split("async function findImage()")[1].split("return { findImage };")[0]

    # The append only happens on the success path; the error path never
    # touches the recipe-images input, so a pasted image survives a failure.
    assert "recipeImages.append([file])" in find_image
    catch_block = find_image.split("} catch (error) {")[1]
    assert "recipeImages.append" not in catch_block
    assert "ui.setStatus(" in catch_block


def test_find_image_success_attaches_the_file_to_the_existing_picker():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert "fileFromBase64(result.data_base64" in script
    assert "refs.recipeImages.append([file])" in script
    # No separate input or preview path was introduced for the found image.
    assert "findImageInput" not in script
    assert "recipe-editor__find-image-input" not in script


def test_find_image_query_field_is_wired_into_the_markup_and_script():
    markup = (EDITOR_ASSETS / "files.html").read_text(encoding="utf-8")
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert 'class="recipe-editor__find-image-query"' in markup
    assert 'aria-label="Image search query for Find One For Me"' in markup
    assert 'findImageQuery: dialog.querySelector(".recipe-editor__find-image-query")' in script
    # The placeholder is kept in sync with the recipe title at runtime.
    assert "syncPlaceholder" in script
    assert "currentRecipeTitle(refs.textarea) || DEFAULT_QUERY_PLACEHOLDER" in script


def test_find_image_uses_the_query_field_and_falls_back_to_the_title():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")
    find_image = script.split("async function findImage()")[1].split("return { findImage };")[0]

    assert "refs.findImageQuery.value.trim()" in find_image
    # A blank query with a title auto-populates the field with the title.
    assert "refs.findImageQuery.value = title" in find_image
    # A blank query with no title outlines the field and explains why.
    assert "setQueryError(true)" in find_image
    assert "Enter an image search query, or add a recipe title" in find_image
    # The backend receives the query, not the title.
    assert "JSON.stringify({ query })" in script


def test_find_image_query_error_state_is_styled_and_clearable():
    markup = (EDITOR_ASSETS / "files.html").read_text(encoding="utf-8")
    css = (EDITOR_ASSETS / "recipe-editor.css").read_text(encoding="utf-8")
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert ".recipe-editor__find-image-query.is-error" in css
    assert "var(--danger-color)" in css.split(".recipe-editor__find-image-query.is-error {")[1].split("}")[0]
    # The error state is cleared as the user types and before a new search.
    assert 'refs.findImageQuery.addEventListener("input"' in script
    assert 'removeAttribute("aria-invalid")' in script
    assert "setQueryError(false)" in script


def test_find_image_query_field_is_disabled_while_searching_or_busy():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert "refs.findImageQuery.disabled = value || state.busy" in script
    assert "refs.findImageQuery.disabled = value;" in script


def test_find_image_button_text_matches_its_accessible_name():
    markup = (EDITOR_ASSETS / "files.html").read_text(encoding="utf-8")
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert '<span class="recipe-editor__find-image-text">Find One For Me</span>' in markup
    assert '"Searching…" : "Find One For Me"' in script


def test_search_images_filters_candidates_whose_source_file_is_a_pdf(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "1": commons_page(
                    "File:Cookbook.pdf",  # PDF pages get .pdf.jpg thumbnails; rejected by the title extension
                    url="https://upload.wikimedia.org/wikipedia/commons/c/cookbook.pdf",
                    thumburl="https://thumb.wikimedia.org/wikipedia/commons/thumb/c/cookbook.pdf/1024px-cookbook.pdf.jpg",
                    index=1,
                ),
                "2": commons_page("File:Dish.jpg", url="https://upload.wikimedia.org/wikipedia/commons/d/dish.jpg", index=2),
            }
        }
    }
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    candidates = image_search.search_images("teriyaki")

    assert [candidate.url for candidate in candidates] == ["https://upload.wikimedia.org/wikipedia/commons/d/dish.jpg"]


def test_search_images_optimizes_noise_words_out_of_the_query(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=10):
        seen["url"] = request.full_url
        payload = {"query": {"pages": {"1": commons_page("File:Dish.jpg", url="https://upload.wikimedia.org/wikipedia/commons/d/dish.jpg", index=1)}}}
        return _FakeSearchResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(image_search, "urlopen", fake_urlopen)
    image_search.search_images("BEST Teriyaki Sauce Recipe")

    assert "gsrsearch=teriyaki+sauce" in seen["url"]
    assert "BEST" not in seen["url"]


def test_optimize_query_falls_back_to_the_raw_query_when_all_words_are_noise():
    assert image_search._optimize_query("the recipe") == "the recipe"
    assert image_search._optimize_query("Chocolate Cake") == "chocolate cake"


def test_search_images_rejects_small_files_served_as_unscaled_thumbnails(monkeypatch):
    # Commons serves the original as the thumbnail for files smaller than the
    # requested width, but still reports thumbwidth as the requested size.
    payload = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Brownies 2010.jpg",
                    "index": 1,
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/2/2c/Brownies_2010.jpg?utm_source=x",
                            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/2/2c/Brownies_2010.jpg?utm_source=y",
                            "thumbwidth": 1024,
                            "thumbheight": 682,
                            "width": 500,
                            "height": 333,
                            "extmetadata": {},
                        }
                    ],
                },
                "2": commons_page(
                    "File:Real.jpg",
                    url="https://upload.wikimedia.org/wikipedia/commons/r/real.jpg",
                    thumburl="https://thumb.wikimedia.org/wikipedia/commons/thumb/r/real.jpg/1024px-real.jpg",
                    thumbwidth=1024,
                    thumbheight=768,
                    index=2,
                ),
                "3": commons_page(
                    "File:Original.jpg", url="https://upload.wikimedia.org/wikipedia/commons/o/original.jpg", width=5000, height=4000, index=3
                ),
            }
        }
    }
    monkeypatch.setattr(image_search, "urlopen", lambda request, timeout=10: _FakeSearchResponse(json.dumps(payload).encode("utf-8")))

    candidates = image_search.search_images("brownies")

    # The small "1024px-reported" original is filtered out; the rest are kept.
    assert [candidate.url for candidate in candidates] == [
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/r/real.jpg/1024px-real.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/o/original.jpg",
    ]
    # A real thumbnail candidate keeps the thumbnail dimensions.
    assert candidates[0].width == 1024
    assert candidates[0].height == 768
    # An original with no thumbnail keeps the original dimensions.
    assert candidates[1].width == 5000
    assert candidates[1].height == 4000


def test_download_image_sends_a_descriptive_user_agent(monkeypatch):
    received = {}

    class _CapturingHandler(BaseHTTPRequestHandler):
        body = png_image()

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            received["user_agent"] = self.headers.get("User-Agent")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(self.body)))
            self.end_headers()
            self.wfile.write(self.body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CapturingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(image_download, "validate_external_url", lambda url: url)
    try:
        image_download.download_image(f"http://127.0.0.1:{server.server_port}/image.png")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert "RecipeServer/0.1" in received["user_agent"]
    assert "https://github.com/fordaj/RecipeServer" in received["user_agent"]
