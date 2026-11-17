"""Tests for the metadata options endpoint and the editor's dropdown fields.

The recipe editor offers the values that are already used in the recipe
library as dropdown options, with the number of recipes that use them. They
are collected from the recipe Markdown files when they are asked for, so
they are never hard-coded into generated pages or recipe front matter.
"""

from pathlib import Path

from test.helpers import request_json, running_recipe_server, write_recipe

DROPDOWN_FIELDS = (
    "meals",
    "categories",
    "cuisine",
    "tags",
    "status",
    "contributor",
    "commenters",
    "raters",
    "source.author",
    "source.title",
)


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
source:
  author: Kailey
  title: The Baking Book
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
source:
  author: Kailey
  title: Some Website
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
            "commenters": [],
            "raters": [],
            "source.author": [{"value": "Kailey", "count": 2}],
            "source.title": [{"value": "Some Website", "count": 1}, {"value": "The Baking Book", "count": 1}],
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


def test_metadata_options_collect_source_author_and_title(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    write_recipe(source / "book" / "recipe.md", "source:\n  author: Kailey\n  title: The Baking Book\n")
    # Older recipes may store the source as a one-item list.
    write_recipe(source / "legacy" / "recipe.md", "source:\n  - author: Avery\n    title: The Baking Book\n")
    # A recipe with no usable source contributes nothing.
    write_recipe(source / "empty" / "recipe.md", "source:\n  author: ''\n")
    write_recipe(source / "missing" / "recipe.md", "meals:\n  - Dinner\n")

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body["options"]["source.author"] == [
        {"value": "Avery", "count": 1},
        {"value": "Kailey", "count": 1},
    ]
    assert body["options"]["source.title"] == [{"value": "The Baking Book", "count": 2}]


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


def test_metadata_options_collect_commenters_and_raters(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    write_recipe(
        source / "dinner" / "recipe.md",
        """comments:
  - id: c1
    author: Avery
    text: Great
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
  - id: c2
    author: Blake
    text: Nice
    created: "2026-01-02T00:00:00.000Z"
    updated: "2026-01-02T00:00:00.000Z"
  - id: c3
    author: Avery
    text: Twice
    created: "2026-01-03T00:00:00.000Z"
    updated: "2026-01-03T00:00:00.000Z"
ratings:
  - id: r1
    name: Avery
    rating: 8
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
""",
    )
    write_recipe(
        source / "dessert" / "recipe.md",
        """comments:
  - id: c4
    author: avery
    text: Also great
    created: "2026-01-04T00:00:00.000Z"
    updated: "2026-01-04T00:00:00.000Z"
ratings:
  - id: r2
    name: Blake
    rating: 9
    created: "2026-01-04T00:00:00.000Z"
    updated: "2026-01-04T00:00:00.000Z"
""",
    )

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    # A recipe counts once per name, compared case-insensitively; the values
    # are offered with the spelling the library already uses.
    assert body["options"]["commenters"] == [
        {"value": "Avery", "count": 1},
        {"value": "avery", "count": 1},
        {"value": "Blake", "count": 1},
    ]
    assert body["options"]["raters"] == [{"value": "Avery", "count": 1}, {"value": "Blake", "count": 1}]


def test_metadata_options_commenters_and_raters_count_recipes(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    # Two comments by the same person on one recipe still count as one recipe.
    write_recipe(
        source / "dinner" / "recipe.md",
        """comments:
  - id: c1
    author: Avery
    text: One
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
  - id: c2
    author: Avery
    text: Two
    created: "2026-01-02T00:00:00.000Z"
    updated: "2026-01-02T00:00:00.000Z"
ratings:
  - id: r1
    name: Avery
    rating: 8
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
""",
    )
    write_recipe(
        source / "dessert" / "recipe.md",
        """comments:
  - id: c3
    author: Avery
    text: Three
    created: "2026-01-03T00:00:00.000Z"
    updated: "2026-01-03T00:00:00.000Z"
ratings:
  - id: r2
    name: Avery
    rating: 9
    created: "2026-01-03T00:00:00.000Z"
    updated: "2026-01-03T00:00:00.000Z"
""",
    )

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body["options"]["commenters"] == [{"value": "Avery", "count": 2}]
    assert body["options"]["raters"] == [{"value": "Avery", "count": 2}]


def test_metadata_options_skip_feedback_entries_with_no_name(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()

    write_recipe(
        source / "dinner" / "recipe.md",
        """comments:
  - id: c1
    author: ""
    text: Anonymous comment
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
  - id: c2
    text: Missing author key
    created: "2026-01-02T00:00:00.000Z"
    updated: "2026-01-02T00:00:00.000Z"
  - not-an-object
ratings:
  - id: r1
    name: ""
    rating: 8
    created: "2026-01-01T00:00:00.000Z"
    updated: "2026-01-01T00:00:00.000Z"
  - id: r2
    rating: 9
    created: "2026-01-02T00:00:00.000Z"
    updated: "2026-01-02T00:00:00.000Z"
  - not-an-object
""",
    )

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/metadata-options")

    assert status == 200
    assert body["options"]["commenters"] == []
    assert body["options"]["raters"] == []
