import re
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
STAR_SLIDER_TEST = Path(__file__).parent / "js" / "ratings_star_slider_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_star_slider_updates_the_score_field():
    result = subprocess.run(
        [shutil.which("node"), str(STAR_SLIDER_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_star_slider_covers_one_to_ten_without_reaching_zero():
    script = (ASSETS / "ratings.js").read_text(encoding="utf-8")
    match = re.search(r"const MIN_SLIDER_SCORE = (\d+);", script)
    maximum = re.search(r"const MAX_SLIDER_SCORE = (\d+);", script)
    assert match and maximum, "the rating script defines the slider range"

    minimum = int(match.group(1))
    highest = int(maximum.group(1))
    assert (minimum, highest) == (1, 10)
    assert minimum > 0, "the slider never selects zero"


def test_star_slider_is_styled_as_an_interactive_control():
    css = (ASSETS / "ratings.css").read_text(encoding="utf-8")

    assert ".recipe-rating__stars--slider" in css
    assert "cursor: pointer;" in css
    assert "touch-action: none;" in css


def declaration_block(css: str, selector: str) -> str:
    marker = f"{selector} {{"
    assert marker in css, f"{selector} is missing from the stylesheet"
    return css.split(marker, 1)[1].split("}", 1)[0]


def test_rating_fields_are_big_enough_that_ios_does_not_zoom_in():
    # iOS Safari zooms the page in when a focused field is smaller than 16
    # pixels, and it never zooms back out again.
    css = (ASSETS / "ratings.css").read_text(encoding="utf-8")

    for selector in (
        ".recipe-rating__author-input",
        ".recipe-rating-form__meta input",
        '.recipe-rating-form__meter input[type="text"]',
    ):
        assert "font-size: 1rem;" in declaration_block(css, selector), selector


def test_comment_name_field_is_big_enough_that_ios_does_not_zoom_in():
    css = (ASSETS / "comments.css").read_text(encoding="utf-8")

    assert "font-size: 1rem;" in declaration_block(css, ".recipe-comment__meta input.recipe-comment__author-input")
