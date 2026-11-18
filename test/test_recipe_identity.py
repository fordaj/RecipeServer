"""Tests for stable recipe identity (``recipe_id`` front matter)."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import frontmatter
import pytest

from recipeserver.core import Core
from recipeserver.recipe_utils import extract_recipe_id, is_valid_recipe_id, set_recipe_id
from test.helpers import running_recipe_server, request_json

# ----- Text-level helpers ---------------------------------------------------


def test_extract_recipe_id_returns_none_for_missing_or_invalid_values():
    assert extract_recipe_id("# No front matter anywhere\n") is None
    assert extract_recipe_id("---\nmeals:\n  - Dinner\n---\n# Title\n") is None
    assert extract_recipe_id("---\nrecipe_id: not-a-uuid\n---\n# Title\n") is None


def test_extract_recipe_id_accepts_quoted_and_unquoted_uuids():
    value = "123e4567-e89b-42d3-a456-426655440000"
    assert extract_recipe_id(f"---\nrecipe_id: {value}\n---\n# Title\n") == value
    assert extract_recipe_id(f'---\nrecipe_id: "{value}"\n---\n# Title\n') == value


def test_set_recipe_id_inserts_into_existing_front_matter_preserving_the_body():
    content = "---\nmeals:\n  - Dinner\n# a comment\n---\n# Title\n\nBody.\n"
    updated = set_recipe_id(content, "123e4567-e89b-42d3-a456-426655440000")
    assert "recipe_id: 123e4567-e89b-42d3-a456-426655440000\n" in updated
    assert updated.endswith("# Title\n\nBody.\n")
    assert "meals:\n  - Dinner\n# a comment\n" in updated


def test_set_recipe_id_prepends_front_matter_when_missing():
    content = "# Title\n\nBody.\n"
    updated = set_recipe_id(content, "123e4567-e89b-42d3-a456-426655440000")
    assert updated.startswith("---\nrecipe_id: 123e4567-e89b-42d3-a456-426655440000\n---\n")
    assert updated.endswith(content)


def test_set_recipe_id_replaces_an_existing_line_in_place():
    content = "---\nrecipe_id: 123e4567-e89b-42d3-a456-426655440000\nmeals: []\n---\n# Title\n"
    updated = set_recipe_id(content, "123e4567-e89b-42d3-a456-426655440001")
    assert "123e4567-e89b-42d3-a456-426655440000" not in updated
    assert "recipe_id: 123e4567-e89b-42d3-a456-426655440001\nmeals:" in updated


def test_set_recipe_id_preserves_crlf_documents():
    content = "---\r\nmeals:\r\n  - Dinner\r\n---\r\n# Title\r\n"
    updated = set_recipe_id(content, "123e4567-e89b-42d3-a456-426655440000")
    assert "\n" not in updated.replace("\r\n", "")
    assert "recipe_id: 123e4567-e89b-42d3-a456-426655440000\r\n" in updated


def test_is_valid_recipe_id_round_trips_set_recipe_id():
    updated = set_recipe_id("# Plain\n", "123e4567-e89b-42d3-a456-426655440000")
    extracted = extract_recipe_id(updated)
    assert extracted is not None
    assert is_valid_recipe_id(extracted)


# ----- regen assignment and duplicate resolution ----------------------------


def test_regen_assigns_stable_ids_to_existing_recipes(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    (source / "dinner").mkdir(parents=True)
    (source / "dinner" / "recipe.md").write_text("---\nmeals:\n  - Dinner\n---\n# Greens\n", encoding="utf-8")
    site.mkdir()

    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))
    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    first = frontmatter.loads((source / "dinner" / "recipe.md").read_text(encoding="utf-8")).metadata["recipe_id"]
    assert is_valid_recipe_id(first)

    # A second rebuild keeps the assigned id.
    core.regen()
    assert frontmatter.loads((source / "dinner" / "recipe.md").read_text(encoding="utf-8")).metadata["recipe_id"] == first


def test_regen_resolves_duplicate_recipe_ids_deterministically(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    duplicated = "123e4567-e89b-42d3-a456-426655440000"
    (source / "alpha").mkdir(parents=True)
    (source / "beta").mkdir(parents=True)
    for name in ("alpha", "beta"):
        (source / name / "recipe.md").write_text(
            f"---\nrecipe_id: {duplicated}\nmeals:\n  - Dinner\n---\n# {name.title()}\n",
            encoding="utf-8",
        )
    site.mkdir()

    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))
    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    alpha = frontmatter.loads((source / "alpha" / "recipe.md").read_text(encoding="utf-8")).metadata["recipe_id"]
    beta = frontmatter.loads((source / "beta" / "recipe.md").read_text(encoding="utf-8")).metadata["recipe_id"]
    assert alpha == duplicated  # the path that sorts first keeps the id
    assert beta != duplicated
    assert is_valid_recipe_id(beta)


def test_regen_keeps_unrelated_metadata_and_body_when_assigning_ids(tmp_path: Path, monkeypatch):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    original = "---\nmeals:\n  - Dinner\n# a comment\n---\n\n# Greens\n\nBody with `1 cup` sugar.\n"
    (source / "dinner").mkdir(parents=True)
    (source / "dinner" / "recipe.md").write_text(original, encoding="utf-8")
    site.mkdir()

    monkeypatch.setattr(Core, "copy_assets", staticmethod(lambda site_directory: None))
    core = Core(SimpleNamespace(source_directory=source, site_directory=site))
    core.regen()

    updated = (source / "dinner" / "recipe.md").read_text(encoding="utf-8")
    assert "# a comment\n" in updated
    assert "Body with `1 cup` sugar.\n" in updated
    assert "meals:\n  - Dinner\n" in updated
    assert extract_recipe_id(updated) is not None


# ----- Identity across API saves ---------------------------------------------


def test_editor_save_round_trips_the_recipe_id(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    original = '---\nrecipe_id: 123e4567-e89b-42d3-a456-426655440000\nmeals:\n  - Dinner\nupdatedOn: "2024-06-20T12:30:00Z"\n---\n# Greens\n\nBody.\n'
    recipe = source / "recipe.md"
    recipe.write_text(original, encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(
            f"{base_url}/api/recipe-editor",
            {"path": "recipe.md", "content": "# Greens\n\nBetter body.\n", "metadata": {}},
        )
    assert status == 200
    saved = frontmatter.loads(recipe.read_text(encoding="utf-8"))
    assert saved.metadata["recipe_id"] == "123e4567-e89b-42d3-a456-426655440000"


def test_raw_markdown_save_keeps_identity_and_injects_id_when_missing(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe = source / "recipe.md"
    recipe.write_text("# Old\n", encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(f"{base_url}/api/markdown", {"path": "recipe.md", "content": "# New\n"})

    assert status == 200
    assert is_valid_recipe_id(extract_recipe_id(recipe.read_text(encoding="utf-8")))


def test_create_recipe_assigns_a_fresh_id(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_recipe_server(source) as (base_url, _, _):
        status, _ = request_json(
            f"{base_url}/api/recipe",
            {
                "folder": "soup",
                "createFolder": True,
                "content": "# Soup\n",
                "metadata": {"meals": ["Dinner"]},
            },
        )

    assert status == 201
    created = (source / "soup" / "recipe.md").read_text(encoding="utf-8")
    assert is_valid_recipe_id(extract_recipe_id(created))
