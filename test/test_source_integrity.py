from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import json
from threading import Thread
from typing import Iterator
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import frontmatter
from PIL import Image

from recipeserver.core import Core
from recipeserver.server import RecipeRequestHandler

EDITOR_METADATA = {
    "tags": ["quick"],
    "cuisine": ["Thai"],
    "categories": ["Dinner"],
    "meals": ["Dinner"],
    "makes": 4,
    "difficulty": 3,
    "contributor": "Avery",
    "createdOn": "2024-06-15T12:30:00Z",
    "updatedOn": "2024-06-20T12:30:00Z",
    "source": {"author": "Avery", "title": "Family recipe", "format": "book", "url": ""},
}


def snapshot_tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def write_png(path: Path, color: tuple[int, int, int] = (180, 40, 40)) -> None:
    Image.new("RGB", (8, 8), color).save(path)


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
def running_server(
    source_directory: Path,
    on_markdown_saved=None,
) -> Iterator[tuple[str, list[Path]]]:
    saved_paths: list[Path] = []
    handler = partial(
        RecipeRequestHandler,
        directory=str(source_directory),
        source_directory=source_directory,
        on_markdown_saved=on_markdown_saved if on_markdown_saved is not None else saved_paths.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}", saved_paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_health_endpoint_reports_ok(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_server(source) as (base_url, _):
        status, body = request_json(f"{base_url}/health")
        trailing_slash_status, trailing_slash_body = request_json(f"{base_url}/health/")

    assert status == 200
    assert body == {"status": "ok"}
    assert trailing_slash_status == 200
    assert trailing_slash_body == {"status": "ok"}


def test_editor_save_preserves_unknown_metadata_and_files_and_updates_edit_time(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe_directory = source / "dinner"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text(
        """---
title: Original title
category:
  - Baking
ratings:
  - name: Avery
    rating: 8
    id: rating-1
    created: "2024-06-15T12:30:00Z"
    updated: "2024-06-15T12:30:00Z"
contributor: Avery
createdOn: "2024-06-15T12:30:00Z"
updatedOn: "2024-06-20T12:30:00Z"
meals:
  - Dinner
makes: 4
difficulty: 3
customField: keep me
nutrition:
  calories: 100
---
# Original Title

Original body with `1 cup` sugar.
""",
        encoding="utf-8",
    )
    write_png(recipe_directory / "image.png")
    (recipe_directory / "notes.txt").write_text("keep these notes", encoding="utf-8")
    before = snapshot_tree(source)

    with running_server(source) as (base_url, saved_paths):
        status, editor = request_json(f"{base_url}/api/recipe-editor?{urlencode({'path': 'dinner/recipe.md'})}")
        assert status == 200
        assert editor["metadata"]["categories"] == ["Baking"]
        assert editor["content"].strip() == "# Original Title\n\nOriginal body with `1 cup` sugar."

        status, body = request_json(
            f"{base_url}/api/recipe-editor",
            {
                "path": "dinner/recipe.md",
                "content": "# Updated Title\n\nUpdated body.\n",
                "metadata": EDITOR_METADATA,
            },
        )

    assert status == 200
    assert body == {"success": True}
    assert saved_paths == [recipe.resolve()]

    post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
    assert post.metadata["customField"] == "keep me"
    assert post.metadata["nutrition"] == {"calories": 100}
    assert post.metadata["ratings"] == [
        {
            "name": "Avery",
            "rating": 8,
            "id": "rating-1",
            "created": "2024-06-15T12:30:00Z",
            "updated": "2024-06-15T12:30:00Z",
        }
    ]
    assert post.metadata["categories"] == ["Dinner"]
    assert "category" not in post.metadata
    assert post.metadata["tags"] == ["quick"]
    assert post.metadata["cuisine"] == ["Thai"]
    assert post.metadata["source"] == {
        "author": "Avery",
        "title": "Family recipe",
        "format": "book",
        "url": None,
    }
    assert post.metadata["updatedOn"] != "2024-06-20T12:30:00Z"
    assert post.content.strip() == "# Updated Title\n\nUpdated body."

    after = snapshot_tree(source)
    assert after.keys() == before.keys()
    assert {path for path in before if before[path] != after[path]} == {"dinner/recipe.md"}


def test_api_serializes_unquoted_yaml_dates(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text(
        """---
createdOn: 2024-06-15
updatedOn: 2024-07-20
---
# Dated Recipe
""",
        encoding="utf-8",
    )

    with running_server(source) as (base_url, _):
        status, metadata = request_json(f"{base_url}/api/metadata/createdOn?{urlencode({'path': 'recipe.md'})}")
        assert status == 200
        assert metadata == {"value": "2024-06-15"}

        status, editor = request_json(f"{base_url}/api/recipe-editor?{urlencode({'path': 'recipe.md'})}")
        assert status == 200
        assert editor["metadata"]["createdOn"] == "2024-06-15"
        assert editor["metadata"]["updatedOn"] == "2024-07-20"


def test_editor_get_returns_json_error_for_malformed_front_matter(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    (source / "recipe.md").write_text(
        "---\nmeals: [\n---\n# Broken Recipe\n",
        encoding="utf-8",
    )

    with running_server(source) as (base_url, _):
        status, body = request_json(f"{base_url}/api/recipe-editor?{urlencode({'path': 'recipe.md'})}")

    assert status == 500
    assert body == {"error": "Unable to parse YAML front matter"}


def test_editor_save_updates_first_source_and_preserves_remaining_sources(tmp_path: Path):
    source = tmp_path / "recipes"
    recipe_directory = source / "dinner"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text(
        """---
meals:
  - Dinner
source:
  - author: Avery
    title: First source
    format: book
    url: ""
  - author: Someone Else
    title: Second source
    format: website
    url: https://example.com/second
---
# Sourced Recipe
""",
        encoding="utf-8",
    )

    with running_server(source) as (base_url, saved_paths):
        status, _ = request_json(
            f"{base_url}/api/recipe-editor",
            {
                "path": "dinner/recipe.md",
                "content": "# Sourced Recipe\n",
                "metadata": {
                    **EDITOR_METADATA,
                    "source": {
                        "author": "Avery",
                        "title": "Updated first source",
                        "format": "book",
                        "url": "",
                    },
                },
            },
        )
        assert status == 200

        status, _ = request_json(
            f"{base_url}/api/recipe-editor",
            {
                "path": "dinner/recipe.md",
                "content": "# Sourced Recipe\n",
                "metadata": {**EDITOR_METADATA, "source": None},
            },
        )
        assert status == 200

    assert saved_paths == [recipe.resolve(), recipe.resolve()]

    post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
    assert post.metadata["source"] == [
        {
            "author": "Someone Else",
            "title": "Second source",
            "format": "website",
            "url": "https://example.com/second",
        }
    ]


def test_metadata_save_updates_only_requested_fields_and_leaves_edit_time_alone(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text(
        """---
category:
  - Baking
ratings:
  - name: Avery
    rating: 8
    id: rating-1
    created: "2024-06-15T12:30:00Z"
    updated: "2024-06-15T12:30:00Z"
comments:
  - text: Existing comment
contributor: Avery
updatedOn: "2024-06-20T12:30:00Z"
customField: keep me
---
# Soup

Body with `1 cup` water.
""",
        encoding="utf-8",
    )
    before = snapshot_tree(source)

    with running_server(source) as (base_url, saved_paths):
        status, legacy = request_json(f"{base_url}/api/metadata/category?{urlencode({'path': 'recipe.md'})}")
        assert status == 200
        assert legacy == {"value": ["Baking"]}

        status, _ = request_json(
            f"{base_url}/api/metadata/comments",
            {"path": "recipe.md", "value": [{"text": "New comment"}]},
        )
        assert status == 200

        status, _ = request_json(
            f"{base_url}/api/metadata/category",
            {"path": "recipe.md", "value": ["Soup"]},
        )
        assert status == 200

    assert saved_paths == [recipe.resolve(), recipe.resolve()]

    post = frontmatter.loads(recipe.read_text(encoding="utf-8"))
    assert post.metadata["comments"] == [{"text": "New comment"}]
    assert post.metadata["categories"] == ["Soup"]
    assert "category" not in post.metadata
    assert post.metadata["ratings"][0]["name"] == "Avery"
    assert post.metadata["customField"] == "keep me"
    assert post.metadata["updatedOn"] == "2024-06-20T12:30:00Z"
    assert post.content.strip() == "# Soup\n\nBody with `1 cup` water."

    after = snapshot_tree(source)
    assert after.keys() == before.keys()
    assert {path for path in before if before[path] != after[path]} == {"recipe.md"}


def test_api_rejects_paths_outside_the_source_directory_without_touching_files(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("---\nmeals: []\n---\n# Outside\n", encoding="utf-8")
    outside_before = outside.read_bytes()

    # Handle platform-specific issue with symbolic links on Windows
    import sys

    try:
        (source / "escape.md").symlink_to(outside)
        symlink_created = True
    except OSError:
        # On Windows, symlink creation may fail due to permissions
        if sys.platform == "win32":
            # Skip the test on Windows when symlink creation fails
            return
        else:
            raise

    # Only run the rest of the test if symlink was created successfully
    if not symlink_created:
        return

    bad_paths = [
        "",
        "../outside.md",
        "nested/../../outside.md",
        "notes.txt",
        "back\\slash.md",
        str(outside),
        "escape.md",
    ]

    with running_server(source) as (base_url, saved_paths):
        for path in bad_paths:
            status, _ = request_json(f"{base_url}/api/markdown?{urlencode({'path': path})}")
            assert status == 400, path

            for endpoint, payload in (
                ("/api/markdown", {"path": path, "content": "# Overwritten\n"}),
                ("/api/metadata/comments", {"path": path, "value": []}),
                (
                    "/api/recipe-editor",
                    {"path": path, "content": "# Overwritten\n", "metadata": {}},
                ),
            ):
                status, _ = request_json(f"{base_url}{endpoint}", payload)
                assert status == 400, (endpoint, path)

    assert saved_paths == []
    assert outside.read_bytes() == outside_before
    assert not (tmp_path / "outside.html").exists()


def test_regen_builds_site_without_modifying_the_source_tree(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    dinner = source / "dinner"
    dessert = source / "dessert" / "nested"
    dinner.mkdir(parents=True)
    dessert.mkdir(parents=True)

    (dinner / "recipe.md").write_text(
        "---\nmeals:\n  - Dinner\n---\n# Braised Greens\n\n![Greens](image.png)\n",
        encoding="utf-8",
    )
    write_png(dinner / "image.png")
    (dinner / "notes.txt").write_text("not part of the site", encoding="utf-8")

    (dessert / "recipe.md").write_text(
        "---\nmeals:\n  - Dessert\n---\n# Peach Cobbler\n",
        encoding="utf-8",
    )
    (dessert / "shopping-list.md").write_text("- peaches\n", encoding="utf-8")

    before = snapshot_tree(source)

    site.mkdir()
    (site / "stale.txt").write_text("delete me", encoding="utf-8")

    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))

    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    after = snapshot_tree(source)
    assert after == before

    assert not (site / "stale.txt").exists()
    assert not (site / "dinner" / "notes.txt").exists()
    assert not (site / "dinner" / "recipe.md").exists()
    assert (site / "dinner" / "image.png").read_bytes() == (dinner / "image.png").read_bytes()
    assert (site / "dinner" / "recipe.html").is_file()
    assert (site / "dessert" / "nested" / "recipe.html").is_file()

    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Braised Greens" in index
    assert "Peach Cobbler" in index
    assert "/dinner/recipe.html" in index
    assert "/dessert/nested/recipe.html" in index

    recipe_html = (site / "dinner" / "recipe.html").read_text(encoding="utf-8")
    assert "Braised Greens" in recipe_html
    assert 'src="/assets/recipe-editor/recipe-editor.js"' in recipe_html


def test_regen_skips_a_recipe_that_fails_to_convert(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    good = source / "good"
    broken = source / "broken"
    good.mkdir(parents=True)
    broken.mkdir(parents=True)

    (good / "recipe.md").write_text(
        "---\nmeals:\n  - Dinner\n---\n# Good Recipe\n",
        encoding="utf-8",
    )
    (broken / "recipe.md").write_text(
        "---\nmeals:\n  - Dinner\n---\n# Broken Recipe\n",
        encoding="utf-8",
    )

    original_convert_recipe = Core.convert_recipe

    def convert_or_fail(core: Core, markdown: Path):
        if markdown.parent.name == "broken":
            raise ValueError("invalid recipe")
        return original_convert_recipe(core, markdown)

    monkeypatch.setattr(Core, "convert_recipe", convert_or_fail)
    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))

    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    assert (site / "good" / "recipe.html").is_file()
    assert not (site / "broken" / "recipe.html").exists()

    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Good Recipe" in index
    assert "Broken Recipe" not in index


def test_editor_save_regenerates_the_recipe_page_and_index(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "dinner"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text(
        "---\nmeals:\n  - Dinner\n---\n# Old Title\n\n![Dinner](image.png)\n",
        encoding="utf-8",
    )
    write_png(recipe_directory / "image.png")

    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))
    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    assert "Old Title" in (site / "dinner" / "recipe.html").read_text(encoding="utf-8")
    assert "Old Title" in (site / "index.html").read_text(encoding="utf-8")

    with running_server(source, on_markdown_saved=core.on_markdown_save) as (base_url, _):
        status, body = request_json(
            f"{base_url}/api/recipe-editor",
            {
                "path": "dinner/recipe.md",
                "content": "# New Title\n\n![Dinner](image.png)\n",
                "metadata": EDITOR_METADATA,
            },
        )

    assert status == 200
    assert body == {"success": True}

    recipe_html = (site / "dinner" / "recipe.html").read_text(encoding="utf-8")
    index_html = (site / "index.html").read_text(encoding="utf-8")
    assert "New Title" in recipe_html
    assert "New Title" in index_html
    assert "Old Title" not in recipe_html
    assert "Old Title" not in index_html
    assert 'src="/dinner/image.png"' in index_html
