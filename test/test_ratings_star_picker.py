import re
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
STAR_PICKER_TEST = Path(__file__).parent / "js" / "ratings_star_picker_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_star_picker_updates_the_score_field():
    result = subprocess.run(
        [shutil.which("node"), str(STAR_PICKER_TEST)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_star_scores_are_the_even_values_from_two_to_ten():
    script = (ASSETS / "ratings.js").read_text(encoding="utf-8")
    match = re.search(r"const STAR_SCORES = \[([^\]]*)\];", script)
    assert match, "the rating script defines the score of every star"

    scores = [int(value) for value in match.group(1).split(",") if value.strip()]
    assert scores == [2, 4, 6, 8, 10]
    assert 0 not in scores


def test_star_picker_is_styled_as_an_interactive_control():
    css = (ASSETS / "ratings.css").read_text(encoding="utf-8")

    assert ".recipe-rating__star-picker" in css
    assert ".recipe-rating__star {" in css
    assert "cursor: pointer;" in css
