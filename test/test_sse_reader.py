"""The browser SSE reader is shared by the recipe editor and the assistant."""

from pathlib import Path
import shutil
import subprocess

import pytest

TEST_JS = Path(__file__).parent / "js" / "sse_test.js"
ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_shared_sse_reader_parses_and_flushes_frames():
    result = subprocess.run([shutil.which("node"), str(TEST_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sse reader checks passed" in result.stdout


def test_both_consumers_delegate_to_the_shared_reader():
    for relative in ("recipe-editor/recipe-editor.js", "ai-assistant/ai-assistant.js"):
        source = (ASSETS / relative).read_text(encoding="utf-8")
        assert "window.RecipeSSE.readEventStream" in source
        assert "buffer.indexOf" not in source


def test_generated_pages_load_the_reader_before_both_consumers(tmp_path):
    from types import SimpleNamespace

    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
    from recipeserver.markdown_to_html import MarkdownToHTMLConverter

    page = tmp_path / "r" / "recipe.html"
    page.parent.mkdir()
    page.write_text("<h1>R</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["R"]}, page))
    generator.convert()
    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")

    source = tmp_path / "src" / "r"
    source.mkdir(parents=True)
    markdown = source / "recipe.md"
    markdown.write_text("# R\n", encoding="utf-8")
    site = tmp_path / "site"
    recipe_html = site / "r" / "recipe.html"
    recipe_html.parent.mkdir(parents=True)
    MarkdownToHTMLConverter(SimpleNamespace(source_directory=tmp_path / "src", site_directory=site)).convert(markdown, recipe_html)

    for html in (index_html, recipe_html.read_text(encoding="utf-8")):
        sse = html.index("/assets/sse.js")
        assert sse < html.index("/assets/ai-assistant/ai-assistant.js")
        assert sse < html.index("/assets/recipe-editor/recipe-editor.js")
