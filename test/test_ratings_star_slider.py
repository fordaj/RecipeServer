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
    css = (ASSETS / "feedback.css").read_text(encoding="utf-8")

    assert ".recipe-rating__stars--slider" in css
    assert "cursor: pointer;" in css
    assert "touch-action: none;" in css


def declaration_block(css: str, selector: str) -> str:
    marker = f"{selector} {{"
    assert marker in css, f"{selector} is missing from the stylesheet"
    return css.split(marker, 1)[1].split("}", 1)[0]


def test_feedback_name_pickers_are_sized_and_styled():
    # The name fields are the shared dropdown widget; the 16-pixel iOS floor
    # is on the shared .field-input rule, which the picker controls use.
    css = (ASSETS / "feedback.css").read_text(encoding="utf-8")
    field_input = declaration_block((ASSETS / "dialog-shell.css").read_text(encoding="utf-8"), ".field-input")

    assert ".recipe-feedback__picker" in css
    assert "width: min(100%, 16rem);" in declaration_block(css, ".recipe-feedback__picker")
    assert "font-size: 1rem;" in field_input


def test_rating_score_field_is_big_enough_that_ios_does_not_zoom_in():
    css = (ASSETS / "feedback.css").read_text(encoding="utf-8")

    meter = declaration_block(css, '.recipe-rating-form__meter input[type="text"]')
    assert "font-size: 1rem;" in meter
    # The shared edit-form rule covers the comment textarea and the score field.
    grouped = css.split(".recipe-comment__edit textarea,", 1)[1].split("}", 1)[0]
    assert "font-size: 1rem;" in grouped
