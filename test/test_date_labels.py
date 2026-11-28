"""One date-label rule across the Python fallback and the browser bundles."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

import pytest

from recipeserver.recipe_utils import display_date

TEST_JS = Path(__file__).parent / "js" / "date_labels_test.js"
ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"


def test_display_date_omits_the_current_year_and_includes_old_years():
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    assert display_date(datetime(2026, 11, 28, 9, 30, tzinfo=timezone.utc), now=now) == "Nov 28"
    assert display_date(datetime(2025, 11, 28, 9, 30, tzinfo=timezone.utc), now=now) == "Nov 28, 2025"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_labels_match_the_python_fallback():
    result = subprocess.run([shutil.which("node"), str(TEST_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    labels = json.loads(result.stdout.strip().splitlines()[-1])

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    assert labels["sameYear"] == display_date(datetime(2026, 11, 28, 9, 30, tzinfo=timezone.utc), now=now)
    assert labels["otherYear"] == display_date(datetime(2025, 11, 28, 9, 30, tzinfo=timezone.utc), now=now)


def test_browser_consumers_delegate_to_the_shared_labels():
    for relative in ("time.js", "recipe-history/timeline.js"):
        source = (ASSETS / relative).read_text(encoding="utf-8")
        assert "RecipeDates" in source
        assert "Intl.DateTimeFormat" not in source


def test_generated_pages_load_labels_before_the_consumers():
    from types import SimpleNamespace

    from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
    from recipeserver.markdown_to_html.page import build_recipe_html

    page = Path(__file__).parent / "tmp-date-labels" / "recipe.html"
    page.parent.mkdir(exist_ok=True)
    page.write_text("<h1>R</h1>", encoding="utf-8")
    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=page.parent.parent))
    generator.add(Recipe({"categories": ["R"]}, page))
    generator.convert()
    index_html = (page.parent.parent / "index.html").read_text(encoding="utf-8")
    assert index_html.index("/assets/date-labels.js") < index_html.index("/assets/time.js")

    recipe_html = build_recipe_html(
        source_title="R",
        heading_color="#8d5542",
        metadata_json="{}",
        recipe_scaler_html="",
        body="<h1>R</h1>",
        ratings_html="",
        comments_html="",
    )
    assert recipe_html.index("/assets/date-labels.js") < recipe_html.index("/assets/time.js")
