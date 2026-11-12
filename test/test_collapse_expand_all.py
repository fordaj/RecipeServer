import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from recipeserver.markdown_to_html import MarkdownToHTMLConverter

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
COLLAPSE_ALL_TEST = Path(__file__).parent / "js" / "collapse_expand_all_test.js"


def convert_recipe(tmp_path: Path, content: str) -> str:
    """Render a recipe and return the HTML of the page."""
    source = tmp_path / "recipes"
    site = tmp_path / "site"
    recipe_directory = source / "pancakes"
    recipe_directory.mkdir(parents=True)

    recipe = recipe_directory / "recipe.md"
    recipe.write_text(content, encoding="utf-8")

    html_file = site / "pancakes" / "recipe.html"
    html_file.parent.mkdir(parents=True)

    converter = MarkdownToHTMLConverter(SimpleNamespace(source_directory=source, site_directory=site))
    converter.convert(recipe, html_file)

    return html_file.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_button_collapses_and_expands_every_section():
    result = subprocess.run(
        [shutil.which("node"), str(COLLAPSE_ALL_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_title_is_left_alone(tmp_path: Path):
    html = convert_recipe(tmp_path, "# Pancakes\n\n## Ingredients\n\n- flour\n")
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h1")
    assert heading is not None
    assert heading.get_text(" ", strip=True) == "Pancakes"
    assert heading.parent.name == "main", "the title is not wrapped for a button"
    assert soup.select_one(".recipe-title__toggle") is None


def test_ratings_and_comments_stay_outside_the_sections(tmp_path: Path):
    html = convert_recipe(tmp_path, "# Pancakes\n\n## Ingredients\n\n- flour\n")
    soup = BeautifulSoup(html, "html.parser")

    for selector in (".recipe-ratings", ".recipe-comments", ".recipe-version"):
        block = soup.select_one(selector)
        assert block is not None, selector
        assert "recipe-extras" in block.get("class", []), f"{selector} sits outside the sections"


def declaration_block(css: str, selector: str) -> str:
    marker = f"{selector} {{"
    assert marker in css, f"{selector} is missing from the stylesheet"
    return css.split(marker, 1)[1].split("}", 1)[0]


def test_the_button_sits_at_the_right_of_a_section_heading():
    css = (ASSETS / "style.css").read_text(encoding="utf-8")

    assert ".recipe-sections__toggle" in css
    assert "left: 100%;" in css, "the button sits at the right of the heading"
    assert 'url("/assets/chevrons-up-down.svg")' in css, "the button shows the chevrons of the shared assets"
    assert 'url("/assets/chevrons-down-up.svg")' in css
    assert '.recipe-sections__toggle[data-state="collapsed"]' in css, "the icon follows the state"


def test_the_collapser_of_a_section_stays_on_the_page():
    css = (ASSETS / "style.css").read_text(encoding="utf-8")

    # A narrow page has no margin beside the heading, so the collapser sits
    # inside the heading, which is bumped over to make room for it.
    assert "padding-left: 1em;" in declaration_block(css, ".collapsible-heading")
    assert "left: 0;" in declaration_block(css, ".collapsible-heading::before")

    # A wide page has room beside the heading for the collapser.
    wide = css.split("@media (min-width: 800px)", 1)[1]
    assert "right: 100%;" in wide, "the collapser sits in the margin of a wide page"


def test_the_script_builds_a_button_for_every_section():
    script = (ASSETS / "recipe.js").read_text(encoding="utf-8")

    assert 'button.className = "recipe-sections__toggle"' in script
    assert "heading.append(toggleAll)" in script, "the button sits in the heading"
    assert 'button.setAttribute("aria-label", label)' in script
