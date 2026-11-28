"""One metadata value collector for the index and the editor dropdowns."""

from __future__ import annotations

from types import SimpleNamespace

from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.metadata_options import collect_metadata_options
from recipeserver.recipe_utils import collect_metadata_values


def test_collect_metadata_values_strips_dedups_and_reads_legacy_category():
    values = collect_metadata_values(
        {"tags": [" Dinner ", "Quick", "Dinner", ""], "category": "Legacy", "categories": [" Dessert "], "status": ["planned", "done"]},
        "tags",
        "categories",
        "status",
    )
    assert values == ["Dinner", "Quick", "Dessert", "planned", "done"]


def test_collect_metadata_values_handles_scalars_and_missing_fields():
    assert collect_metadata_values({"tags": "Solo"}, "tags") == ["Solo"]
    assert collect_metadata_values({"tags": 42}, "tags") == []
    assert collect_metadata_values({}, "tags") == []


def test_index_and_dropdowns_agree_on_a_padded_tag(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    markdown = source / "recipe.md"
    markdown.write_text('---\ntags: [" Padded "]\ncategories: [Dinner]\n---\n\n# P\n', encoding="utf-8")

    options = collect_metadata_options(source)
    assert options["tags"] == [{"value": "Padded", "count": 1}]

    page = tmp_path / "site" / "p" / "recipe.html"
    page.parent.mkdir(parents=True)
    page.write_text("<h1>P</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path / "site"))
    generator.add(Recipe({"tags": [" Padded "], "categories": ["Dinner"]}, page))
    generator.convert()
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert 'value="padded"' in index_html
    assert ">Padded</span>" in index_html
