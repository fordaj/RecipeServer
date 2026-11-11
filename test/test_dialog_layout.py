from pathlib import Path

from bs4 import BeautifulSoup

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


def test_recipe_editor_scrolls_its_body_not_the_footer():
    form = (ASSETS / "recipe-editor" / "form.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(form, "html.parser")

    body = soup.select_one("form.recipe-editor > .recipe-editor__body")
    assert body is not None
    assert body.select_one(".recipe-editor__markdown-details") is not None

    # Header and footer sit outside the scrolling body so the actions never
    # move with the content underneath them.
    header = soup.select_one("form.recipe-editor > .recipe-editor__header")
    footer = soup.select_one("form.recipe-editor > .recipe-editor__footer")
    assert header is not None and header.find_parent(class_="recipe-editor__body") is None
    assert footer is not None and footer.find_parent(class_="recipe-editor__body") is None

    status = footer.select_one(".recipe-editor__status")
    assert status is not None
    assert status.find_parent(class_="recipe-editor__body") is None


def test_recipe_editor_css_pins_footer_outside_the_scroll_region():
    css = (ASSETS / "recipe-editor" / "recipe-editor.css").read_text(encoding="UTF-8")

    editor = css.split(".recipe-editor {")[1].split("}")[0]
    assert "overflow: hidden" in editor

    body = css.split(".recipe-editor__body {")[1].split("}")[0]
    assert "flex: 1 1 auto" in body
    assert "overflow-y: auto" in body

    footer = css.split(".recipe-editor__footer {")[1].split("}")[0]
    assert "position: sticky" not in footer
    assert "flex: 0 0 auto" in footer
