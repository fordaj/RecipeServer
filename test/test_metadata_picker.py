import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipeserver.markdown_to_html import MarkdownToHTMLConverter

PICKER_TEST = Path(__file__).parent / "js" / "metadata_picker_test.js"
FIELDS_TEST = Path(__file__).parent / "js" / "fields_test.js"
EDITOR_ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"

# The metadata fields that are filled from a dropdown.
DROPDOWN_FIELDS = ("meals", "categories", "cuisine", "status", "tags", "contributor")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_metadata_picker_offers_existing_values_and_adds_new_ones():
    result = subprocess.run(
        [shutil.which("node"), str(PICKER_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "metadata picker checks passed" in result.stdout


def test_editor_details_use_dropdowns_for_the_metadata_fields():
    details = (EDITOR_ASSETS / "details.html").read_text(encoding="utf-8")
    fields = (EDITOR_ASSETS / "fields.js").read_text(encoding="utf-8")

    for field in DROPDOWN_FIELDS:
        # The dropdown fields render a picker, defined once in fields.js.
        assert f'field: "{field}", picker: true' in fields
        # The dropdown fields are no longer free-text inputs.
        assert f'name: "{field}"' not in fields

    # The fields that are not a list of known values stay plain inputs.
    assert 'name: "makes"' in fields
    assert 'name: "difficulty"' in fields
    assert 'name: "createdOn"' in fields
    # The field groups are mounted by the fragment shells.
    for name, group in (("details.html", "details"), ("sources.html", "sources"), ("ratings.html", "ratings")):
        fragment = (EDITOR_ASSETS / name).read_text(encoding="utf-8")
        assert f'data-field-group="{group}"' in fragment


def test_editor_reads_the_dropdown_options_from_the_api():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert 'const METADATA_OPTIONS_API = "/api/metadata-options"' in script
    assert "await refreshMetadataOptions(ctx)" in script
    assert "refs.pickers.setValues(field, metadataValues(metadata[field]))" in script
    assert "refs.pickers.values(field)" in script


def test_recipe_page_loads_the_metadata_picker_script(tmp_path: Path):
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "recipe"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text("---\nmeals:\n  - Dinner\n---\n# Soup\n\nBody.\n", encoding="utf-8")

    html_file = site / "recipe" / "recipe.html"
    html_file.parent.mkdir(parents=True)
    converter = MarkdownToHTMLConverter(SimpleNamespace(source_directory=source, site_directory=site))
    converter.convert(recipe, html_file)

    html = html_file.read_text(encoding="utf-8")
    assert 'src="/assets/recipe-editor/metadata-picker.js"' in html
    assert 'src="/assets/recipe-editor/recipe-editor.js"' in html
    # The picker has to be loaded before the editor that uses it.
    assert html.index("metadata-picker.js") < html.index("recipe-editor.js")


def test_index_page_loads_the_metadata_picker_script(tmp_path: Path):
    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe

    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "/assets/recipe-editor/metadata-picker.js" in index
    # The bulk editor uses the same dialog, so the picker has to be loaded
    # before the editor that uses it.
    assert index.index("metadata-picker.js") < index.index("recipe-editor.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_editor_fields_build_the_expected_contract():
    result = subprocess.run(
        [shutil.which("node"), str(FIELDS_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "editor fields checks passed" in result.stdout
