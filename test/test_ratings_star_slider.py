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
