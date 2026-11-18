"""API tests for the version-history endpoints and snapshot triggers."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from recipeserver.recipe_utils import extract_recipe_id
from test.helpers import read_metadata, request_json, running_recipe_server


def recipe_text(content: str, recipe_id: str | None = None) -> str:
    id_line = f"recipe_id: {recipe_id}\n" if recipe_id else ""
    return f'---\n{id_line}meals:\n  - Dinner\nupdatedOn: "2024-06-20T12:30:00Z"\n---\n# Soup\n\n{content}\n'


def snapshot_dir(recipe_id: str) -> Path:
    return Path(os.environ["RECIPE_SERVER_HISTORY_DIR"]) / "recipes" / recipe_id


def read_snapshots(recipe_id: str) -> list[Path]:
    directory = snapshot_dir(recipe_id)
    return sorted(directory.glob("*.md")) if directory.is_dir() else []


def test_editor_save_snapshots_the_previous_version_exactly(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    original = recipe_text("Original body.\n", recipe_id)
    recipe.write_text(original, encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe-editor",
            {
                "path": "recipe.md",
                "content": "Updated body.\n",
                "metadata": {},
            },
        )

    assert status == 200
    snapshots = read_snapshots(recipe_id)
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == original


def test_history_list_returns_snapshots_newest_first(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("v1\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        for body_text in ("v2\n", "v3\n"):
            status, _ = request_json(
                f"{base_url}/api/markdown",
                {"path": "recipe.md", "content": f"---\nrecipe_id: {recipe_id}\n---\n# Soup\n\n{body_text}"},
            )
            assert status == 200

        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")

    assert status == 200
    assert payload["recipeId"] == recipe_id
    assert len(payload["snapshots"]) == 2
    assert payload["snapshots"][0]["created"] >= payload["snapshots"][1]["created"]
    assert all(entry["id"] and entry["created"] and entry["size"] > 0 for entry in payload["snapshots"])


def test_unchanged_save_does_not_create_a_snapshot(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("Body.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        payload = {"path": "recipe.md", "content": f"---\nrecipe_id: {recipe_id}\n---\n# Soup\n\nBody.\n"}
        status, _ = request_json(f"{base_url}/api/markdown", payload)
        assert status == 200
        count_after_migration = len(read_snapshots(recipe_id))
        status, _ = request_json(f"{base_url}/api/markdown", payload)
        assert status == 200
        assert len(read_snapshots(recipe_id)) == count_after_migration


def test_editor_save_with_only_updated_on_change_creates_no_snapshot(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("Body.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        for _ in range(2):
            status, _ = request_json(
                f"{base_url}/api/recipe-editor",
                {
                    "path": "recipe.md",
                    "content": "# Soup\n\nBody.\n",
                    "metadata": {"meals": ["Dinner"]},
                },
            )
            assert status == 200

    assert read_snapshots(recipe_id) == []


def test_metadata_save_creates_a_snapshot_and_restore_rolls_it_back(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("Body.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(f"{base_url}/api/metadata/categories", {"path": "recipe.md", "value": ["Soup"]})
        assert status == 200
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")
        snapshot_id = payload["snapshots"][0]["id"]

        status, _ = request_json(
            f"{base_url}/api/history/restore",
            {"path": "recipe.md", "snapshot": snapshot_id},
        )

    assert status == 200
    metadata = read_metadata(recipe)
    assert "categories" not in metadata
    # The restore itself is reversible: the pre-restore state is now a snapshot.
    snapshots = read_snapshots(recipe_id)
    assert len(snapshots) == 2
    assert extract_recipe_id(recipe.read_text(encoding="utf-8")) == recipe_id


def test_compare_returns_a_unified_diff_against_current(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("Body original.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(
            f"{base_url}/api/markdown",
            {"path": "recipe.md", "content": f"---\nrecipe_id: {recipe_id}\n---\n# Soup\n\nBody rewritten.\n"},
        )
        assert status == 200
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")
        snapshot_id = payload["snapshots"][0]["id"]
        status, compare = request_json(f"{base_url}/api/history/compare?{urlencode({'path': 'recipe.md', 'snapshot': snapshot_id})}")

    assert status == 200
    assert "-Body original." in compare["diff"]
    assert "+Body rewritten." in compare["diff"]
    assert compare["snapshot"]["id"] == snapshot_id


def test_preview_renders_the_markdown_and_does_not_modify_the_recipe(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    original = recipe_text("Before preview.\n", recipe_id)
    recipe.write_text(original, encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(
            f"{base_url}/api/markdown",
            {"path": "recipe.md", "content": f"---\nrecipe_id: {recipe_id}\n---\n# Soup\n\nAfter preview.\n"},
        )
        assert status == 200
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")
        snapshot_id = payload["snapshots"][0]["id"]

        with urlopen(f"{base_url}/api/history/preview?{urlencode({'path': 'recipe.md', 'snapshot': snapshot_id})}") as response:
            html = response.read().decode("utf-8")
            assert response.headers.get_content_type() == "text/html"

    assert "Before preview." in html
    assert "<script" not in html
    assert 'class="recipe-header"' not in html
    assert recipe.read_text(encoding="utf-8").endswith("After preview.\n")


def test_restore_to_a_missing_file_recovers_a_deleted_recipe(tmp_path: Path):
    source = tmp_path / "recipes"
    nested = source / "Dinner" / "Soup"
    nested.mkdir(parents=True)
    recipe = nested / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    original = recipe_text("Before delete.\n", recipe_id)
    recipe.write_text(original, encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        # Make a managed change so a snapshot exists.
        status, _ = request_json(
            f"{base_url}/api/markdown",
            {"path": "Dinner/Soup/recipe.md", "content": f"---\nrecipe_id: {recipe_id}\n---\n# Soup\n\nEdited.\n"},
        )
        assert status == 200

        # Delete the recipe through the server, then restore the snapshot.
        status, _ = request_json(f"{base_url}/api/recipe?{urlencode({'path': 'Dinner/Soup/recipe.md'})}", {}, method="DELETE")
        assert status == 200
        assert not recipe.exists()

        # The history is preserved even though the file (and its directory) is gone…
        assert len(read_snapshots(recipe_id)) == 1

        # …and the recipe can be recovered from a snapshot by path + recipeId.
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'Dinner/Soup/recipe.md', 'recipeId': recipe_id})}")
        assert status == 200
        snapshot_id = payload["snapshots"][0]["id"]

        status, _ = request_json(
            f"{base_url}/api/history/restore",
            {"path": "Dinner/Soup/recipe.md", "snapshot": snapshot_id, "recipeId": recipe_id},
        )

    assert status == 200
    assert recipe.is_file()
    assert "Edited." not in recipe.read_text(encoding="utf-8")
    assert "Before delete." in recipe.read_text(encoding="utf-8")
    assert extract_recipe_id(recipe.read_text(encoding="utf-8")) == recipe_id


def test_history_endpoints_reject_invalid_input(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    recipe.write_text(recipe_text("Body.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(f"{base_url}/api/history/preview?{urlencode({'path': 'recipe.md', 'snapshot': 'bogus'})}")
        assert status == 400
        status, _ = request_json(f"{base_url}/api/history/preview?{urlencode({'path': 'recipe.md', 'snapshot': '20261117T123045123456Z-deadbeef'})}")
        assert status == 404
        status, _ = request_json(f"{base_url}/api/history/compare?{urlencode({'path': '../outside.md'})}")
        assert status == 400
        status, _ = request_json(f"{base_url}/api/history/restore", {"path": "recipe.md", "snapshot": "bogus"})
        assert status == 400


def test_history_list_assigns_an_id_to_a_legacy_recipe_without_snapshotting(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    original = "---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n"
    recipe.write_text(original, encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")

    assert status == 200
    recipe_id = payload["recipeId"]
    assert recipe_id
    # The id was injected in place and everything else is byte-identical.
    saved = recipe.read_text(encoding="utf-8")
    assert saved == original.replace("---\n", f"---\nrecipe_id: {recipe_id}\n", 1)
    # No snapshot of the untouched content was created.
    assert read_snapshots(recipe_id) == []


def test_restore_preserves_the_recipe_identity_when_the_content_has_another(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe_id = "123e4567-e89b-42d3-a456-426655440000"
    other_id = "123e4567-e89b-42d3-a456-426655440099"
    recipe.write_text(recipe_text("Body.\n", recipe_id), encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        # Craft a snapshot by hand that carries a different recipe_id line.
        from recipeserver import history

        foreign = recipe_text("Foreign body.\n", other_id)
        history.create_snapshot(recipe_id, foreign)
        status, payload = request_json(f"{base_url}/api/history?{urlencode({'path': 'recipe.md'})}")
        snapshot_id = payload["snapshots"][0]["id"]
        status, _ = request_json(f"{base_url}/api/history/restore", {"path": "recipe.md", "snapshot": snapshot_id})

    assert status == 200
    assert extract_recipe_id(recipe.read_text(encoding="utf-8")) == recipe_id
