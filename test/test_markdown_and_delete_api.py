"""Focused tests for raw markdown and single-recipe delete API endpoints.

These endpoints are exercised indirectly in some integrity tests, but the
happy paths and save/delete-after-regeneration-failure behavior deserve
explicit coverage.
"""

from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Iterator
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from recipeserver.server import RecipeRequestHandler


def request_json(url: str, payload: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    if payload is None:
        request = Request(url, method=method or "GET")
    else:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method or "POST",
        )

    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        body = error.read()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"error": body.decode("utf-8", errors="replace")}
        return error.code, parsed


@contextmanager
def running_server(
    source_directory: Path,
    *,
    on_markdown_saved=None,
    on_recipes_deleted=None,
) -> Iterator[tuple[str, list[Path], list[list[Path]]]]:
    saved_paths: list[Path] = []
    deleted_batches: list[list[Path]] = []

    handler = partial(
        RecipeRequestHandler,
        directory=str(source_directory),
        source_directory=source_directory,
        on_markdown_saved=on_markdown_saved if on_markdown_saved is not None else saved_paths.append,
        on_recipes_deleted=on_recipes_deleted if on_recipes_deleted is not None else deleted_batches.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", saved_paths, deleted_batches
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_markdown_get_returns_raw_content_and_404(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    content = "---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n"
    recipe.write_text(content, encoding="utf-8", newline="\n")

    with running_server(source) as (base_url, _, _):
        with urlopen(f"{base_url}/api/markdown?{urlencode({'path': 'recipe.md'})}") as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "text/markdown"
            assert response.read().decode("utf-8") == content

        status, body = request_json(f"{base_url}/api/markdown?{urlencode({'path': 'missing.md'})}")
        assert status == 404
        assert body == {"error": "Markdown file not found"}


def test_markdown_post_saves_content_and_reports_regeneration_failure(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text("# Old\n", encoding="utf-8")

    with running_server(source) as (base_url, saved_paths, _):
        status, body = request_json(
            f"{base_url}/api/markdown",
            {"path": "recipe.md", "content": "# New\n\nUpdated body.\n"},
        )

    assert status == 200
    assert body == {"success": True}
    assert saved_paths == [recipe.resolve()]
    assert recipe.read_text(encoding="utf-8") == "# New\n\nUpdated body.\n"

    # A callback failure after a successful write must report that the file
    # was saved, matching the behavior used by other save endpoints.
    source2 = tmp_path / "recipes2"
    source2.mkdir()
    recipe2 = source2 / "recipe.md"
    recipe2.write_text("# Old\n", encoding="utf-8")

    def fail_regen(_path):
        raise RuntimeError("regen failed")

    with running_server(source2, on_markdown_saved=fail_regen) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/markdown",
            {"path": "recipe.md", "content": "# Saved Anyway\n"},
        )

    assert status == 500
    assert body == {"error": "Markdown saved, but HTML regeneration failed"}
    assert recipe2.read_text(encoding="utf-8") == "# Saved Anyway\n"


def test_recipe_delete_removes_file_cleans_empty_dir_and_reports_regen_failure(tmp_path: Path):
    source = tmp_path / "recipes"
    nested = source / "Dinner" / "Soup"
    nested.mkdir(parents=True)
    recipe = nested / "recipe.md"
    recipe.write_text("# Soup\n", encoding="utf-8")

    with running_server(source) as (base_url, _, deleted_batches):
        status, body = request_json(
            f"{base_url}/api/recipe?{urlencode({'path': 'Dinner/Soup/recipe.md'})}",
            method="DELETE",
        )

    assert status == 200
    assert body == {"success": True}
    assert not recipe.exists()
    # The recipe's immediate folder is removed when it becomes empty; parent
    # folders are left in place.
    assert not nested.exists()
    assert (source / "Dinner").is_dir()
    assert deleted_batches == [[recipe.resolve()]]

    # Missing file and invalid path are reported explicitly.
    source2 = tmp_path / "recipes2"
    source2.mkdir()
    with running_server(source2) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe?{urlencode({'path': 'missing.md'})}",
            method="DELETE",
        )
        assert status == 404
        assert body == {"error": "Markdown file not found"}

        status, body = request_json(
            f"{base_url}/api/recipe?{urlencode({'path': '../outside.md'})}",
            method="DELETE",
        )
        assert status == 400
        assert "source directory" in body["error"].lower() or "invalid" in body["error"].lower()

    # Deletion callback failure is reported after the file is removed.
    source3 = tmp_path / "recipes3"
    (source3 / "Solo").mkdir(parents=True)
    recipe3 = source3 / "Solo" / "recipe.md"
    recipe3.write_text("# Solo\n", encoding="utf-8")

    def fail_delete(_paths):
        raise RuntimeError("index failed")

    with running_server(source3, on_recipes_deleted=fail_delete) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe?{urlencode({'path': 'Solo/recipe.md'})}",
            method="DELETE",
        )

    assert status == 500
    assert body == {"error": "Recipe deleted, but index regeneration failed"}
    assert not recipe3.exists()


def test_unknown_api_endpoint_returns_404(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/not-a-real-endpoint")
        assert status == 404

        status, body = request_json(f"{base_url}/api/not-a-real-endpoint", {"x": 1})
        assert status == 404
