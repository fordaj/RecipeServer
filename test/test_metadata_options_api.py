"""Tests for the metadata options endpoint and the editor's dropdown fields.

The recipe editor offers the values that are already used in the recipe
library as dropdown options, with the number of recipes that use them. They
are collected from the recipe Markdown files when they are asked for, so
they are never hard-coded into generated pages or recipe front matter.
"""

from pathlib import Path

from test.helpers import request_json, running_recipe_server, write_recipe

DROPDOWN_FIELDS = ("meals", "categories", "cuisine", "tags", "status", "contributor")


def test_metadata_options_collects_the_values_used_by_every_recipe(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    write_recipe(
        source / "dinner" / "recipe.md",
        """tags:
  - quick
  - Chocolate
cuisine:
  - Thai
categories:
  - Dinner
meals:
  - Dinner
contributor: Avery
status: In Rotation
""",
    )
    write_recipe(
        source / "dessert" / "recipe.md",
        """tags:
  - Sweet
cuisine: American
categories:
  - Dessert
meals:
  - Dessert
contributor: Avery
status: Try Me
""",
    )

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body == {
        "options": {
            "meals": [{"value": "Dessert", "count": 1}, {"value": "Dinner", "count": 1}],
            "categories": [{"value": "Dessert", "count": 1}, {"value": "Dinner", "count": 1}],
            "cuisine": [{"value": "American", "count": 1}, {"value": "Thai", "count": 1}],
            "tags": [
                {"value": "Chocolate", "count": 1},
                {"value": "quick", "count": 1},
                {"value": "Sweet", "count": 1},
            ],
            "status": [{"value": "In Rotation", "count": 1}, {"value": "Try Me", "count": 1}],
            "contributor": [{"value": "Avery", "count": 2}],
        }
    }


def test_metadata_options_count_how_many_recipes_use_a_value(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    for index, meal in enumerate(["Dinner", "Dinner", "Breakfast"]):
        write_recipe(source / f"recipe-{index}" / "recipe.md", f"meals:\n  - {meal}\n")

    write_recipe(source / "both" / "recipe.md", "meals:\n  - Dinner\n  - Breakfast\n")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    # Dinner is used by three recipes and Breakfast by two. A recipe that
    # lists the same value twice still only counts once.
    assert body["options"]["meals"] == [
        {"value": "Breakfast", "count": 2},
        {"value": "Dinner", "count": 3},
    ]


def test_metadata_options_include_the_legacy_singular_category_field(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "recipe.md", "category:\n  - Baking\n")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body["options"]["categories"] == [{"value": "Baking", "count": 1}]


def test_metadata_options_are_empty_for_a_library_without_recipes(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body == {"options": {field: [] for field in DROPDOWN_FIELDS}}


def test_metadata_options_skip_recipes_with_broken_front_matter(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "good" / "recipe.md", "meals:\n  - Dinner\n")
    (source / "broken" / "recipe.md").parent.mkdir(parents=True)
    (source / "broken" / "recipe.md").write_text("---\nmeals: [\n---\n# Broken\n", encoding="utf-8")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body["options"]["meals"] == [{"value": "Dinner", "count": 1}]
