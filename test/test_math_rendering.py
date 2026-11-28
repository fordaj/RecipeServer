"""Recipe pages and chat messages must render math for the same KaTeX setup."""

from pathlib import Path
from types import SimpleNamespace

from recipeserver.markdown_to_html import MarkdownToHTMLConverter
from recipeserver.assistant_render import render_chat_markdown


def _recipe_page(tmp_path: Path, body: str) -> str:
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "math"
    recipe_directory.mkdir(parents=True)
    recipe = recipe_directory / "recipe.md"
    recipe.write_text(f"# Math\n\n{body}\n", encoding="utf-8")
    html_file = site / "math" / "recipe.html"
    html_file.parent.mkdir(parents=True)

    converter = MarkdownToHTMLConverter(SimpleNamespace(source_directory=source, site_directory=site))
    converter.convert(recipe, html_file)
    return html_file.read_text(encoding="utf-8")


def test_recipe_page_math_uses_katex_compatible_spans(tmp_path: Path):
    page = _recipe_page(tmp_path, "Inline $x^2$.\n\n$$e^{i\\pi} = -1$$")

    assert 'class="arithmatex">\\(x^2\\)' in page
    assert 'class="arithmatex">\\[e^{i\\pi} = -1\\]' in page
    assert "MathJax_Preview" not in page
    assert "math/tex" not in page


def test_chat_math_uses_the_same_spans():
    html = render_chat_markdown("Inline $x^2$.")

    assert 'class="arithmatex">\\(x^2\\)' in html
