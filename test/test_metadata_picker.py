import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipeserver.markdown_to_html import MarkdownToHTMLConverter

PICKER_TEST = Path(__file__).parent / "js" / "metadata_picker_test.js"
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

    for field in DROPDOWN_FIELDS:
        assert f'<span class="recipe-editor__picker" data-field="{field}"></span>' in details
        # The dropdown fields are no longer free-text inputs.
        assert f'name="{field}"' not in details

    # The fields that are not a list of known values stay plain inputs.
    assert 'name="makes"' in details
    assert 'name="difficulty"' in details
    assert 'name="createdOn"' in details


def test_editor_reads_the_dropdown_options_from_the_api():
    script = (EDITOR_ASSETS / "recipe-editor.js").read_text(encoding="utf-8")

    assert 'const METADATA_OPTIONS_API = "/api/metadata-options"' in script
    assert "await refreshMetadataOptions(refs)" in script
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
