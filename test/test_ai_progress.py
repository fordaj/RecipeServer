import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipeserver.markdown_to_html import MarkdownToHTMLConverter

PROGRESS_TEST = Path(__file__).parent / "js" / "ai_progress_test.js"
EDITOR_ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets" / "recipe-editor"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ai_progress_shows_status_and_metrics():
    result = subprocess.run(
        [shutil.which("node"), str(PROGRESS_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ai progress checks passed" in result.stdout


def test_ai_progress_markup_has_status_and_metrics_only():
    markup = (EDITOR_ASSETS / "ai.html").read_text(encoding="utf-8")

    assert 'class="recipe-editor__ai-status"' in markup
    assert 'role="status"' in markup
    assert 'class="recipe-editor__ai-progress" hidden' in markup
    assert 'class="recipe-editor__ai-metrics" hidden' in markup
    for metric in ("model-load", "generation", "tokens", "rate"):
        assert f"recipe-editor__ai-metric-{metric}" in markup

    # The generated Markdown is reviewed in the editor below the AI section,
    # so there is no separate thinking or content preview.
    assert "recipe-editor__ai-thinking" not in markup
    assert "recipe-editor__ai-preview" not in markup


def test_recipe_page_loads_the_ai_progress_script_before_the_editor(tmp_path: Path):
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
    assert 'src="/assets/recipe-editor/ai-progress.js"' in html
    assert 'src="/assets/recipe-editor/recipe-editor.js"' in html
    # The editor reads window.RecipeAIProgress, so the module must load first.
    assert html.index("ai-progress.js") < html.index("recipe-editor.js")


def test_index_page_loads_the_ai_progress_script_before_the_editor(tmp_path: Path):
    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe

    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "/assets/recipe-editor/ai-progress.js" in index
    assert "/assets/recipe-editor/recipe-editor.js" in index
    # The bulk editor uses the same dialog and progress module.
    assert index.index("ai-progress.js") < index.index("recipe-editor.js")
