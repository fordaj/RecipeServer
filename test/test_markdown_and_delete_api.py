"""Focused tests for raw markdown and single-recipe delete API endpoints.

These endpoints are exercised indirectly in some integrity tests, but the
happy paths and save/delete-after-regeneration-failure behavior deserve
explicit coverage.
"""

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from test.helpers import request_json, running_recipe_server


def test_markdown_get_returns_raw_content_and_404(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    content = "---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n"
    recipe.write_text(content, encoding="utf-8", newline="\n")

    with running_recipe_server(source) as (base_url, _, _):
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

    with running_recipe_server(source) as (base_url, saved_paths, _):
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

    with running_recipe_server(source2, on_markdown_saved=fail_regen) as (base_url, _, _):
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

    with running_recipe_server(source) as (base_url, _, deleted_batches):
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
    with running_recipe_server(source2) as (base_url, _, _):
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

    with running_recipe_server(source3, on_recipes_deleted=fail_delete) as (base_url, _, _):
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

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/not-a-real-endpoint")
        assert status == 404

        status, body = request_json(f"{base_url}/api/not-a-real-endpoint", {"x": 1})
        assert status == 404
