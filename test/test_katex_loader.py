"""The lazy KaTeX loader is shared by the assistant and the shopping list."""

from pathlib import Path
import shutil
import subprocess

import pytest

TEST_JS = Path(__file__).parent / "js" / "katex_loader_test.js"
ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_shared_katex_loader():
    result = subprocess.run([shutil.which("node"), str(TEST_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "katex loader checks passed" in result.stdout


def test_consumers_delegate_to_the_shared_loader():
    for relative, auto_render in (("ai-assistant/ai-assistant.js", "true"), ("shopping-list/shopping-list.js", "false")):
        source = (ASSETS / relative).read_text(encoding="utf-8")
        assert f"ensureKatex({{ autoRender: {auto_render} }})" in source
        assert "let katexPromise" not in source
        assert "loadScript(" not in source


def test_generated_pages_load_the_loader_before_consumers():
    from types import SimpleNamespace

    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
    from recipeserver.markdown_to_html.page import build_recipe_html

    page = Path(__file__).parent / "tmp-katex-loader" / "recipe.html"
    page.parent.mkdir(exist_ok=True)
    page.write_text("<h1>R</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=page.parent.parent))
    generator.add(Recipe({"categories": ["R"]}, page))
    generator.convert()
    index_html = (page.parent.parent / "index.html").read_text(encoding="utf-8")
    assert index_html.index("/assets/katex-loader.js") < index_html.index("/assets/ai-assistant/ai-assistant.js")

    recipe_html = build_recipe_html(
        source_title="R",
        heading_color="#8d5542",
        metadata_json="{}",
        recipe_scaler_html="",
        body="<h1>R</h1>",
        ratings_html="",
        comments_html="",
    )
    assert recipe_html.index("/assets/katex-loader.js") < recipe_html.index("/assets/ai-assistant/ai-assistant.js")
