"""Tests for the scheduler: the schedule data, its API, and its assets.

A recipe is scheduled by listing calendar dates in its YAML front matter
(``scheduledOn``). The calendar reads that field from every recipe and
writes it back, so the Markdown files stay the source of truth.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from recipeserver.config import DEFAULT_FOOD_COLOR
from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe
from recipeserver.scheduler import (
    normalize_dates,
    parse_dates,
    read_schedules,
    recipe_title,
    write_dates,
)

from test.helpers import read_metadata, request_json, running_recipe_server, write_png

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
SCHEDULER_ASSETS = ASSETS / "scheduler"


# ----- Date handling ----- #


def test_normalize_dates_sorts_and_deduplicates():
    assert normalize_dates(["2026-11-22", "2026-11-15", "2026-11-22"]) == ["2026-11-15", "2026-11-22"]


def test_normalize_dates_accepts_a_single_date():
    assert normalize_dates("2026-11-15") == ["2026-11-15"]


def test_normalize_dates_reads_yaml_date_objects():
    # An unquoted YAML date is read back as a date object.
    assert normalize_dates([date(2026, 11, 15)]) == ["2026-11-15"]


def test_normalize_dates_drops_unreadable_values():
    assert normalize_dates(["not a date", "", None, 7]) == []
    assert normalize_dates(None) == []
    assert normalize_dates({"a": 1}) == []


def test_parse_dates_rejects_a_malformed_date():
    with pytest.raises(ValueError):
        parse_dates(["2026-13-45"])

    with pytest.raises(ValueError):
        parse_dates("2026-11-15")


def test_parse_dates_sorts_and_deduplicates():
    assert parse_dates(["2026-11-22", "2026-11-15", "2026-11-22"]) == ["2026-11-15", "2026-11-22"]


# ----- Titles ----- #


def test_recipe_title_uses_the_heading():
    assert recipe_title("# Soup\n\nBody.", {}, "soup") == "Soup"


def test_recipe_title_falls_back_to_the_front_matter_then_the_folder():
    assert recipe_title("Body only", {"title": "Stew"}, "stew") == "Stew"
    assert recipe_title("Body only", {}, "apple-cake") == "Apple Cake"


def test_recipe_title_ignores_a_heading_inside_a_code_block():
    content = "```\n# Not a title\n```\n\n# Real Title\n"

    assert recipe_title(content, {}, "soup") == "Real Title"


# ----- Reading and writing ----- #


def test_read_schedules_returns_every_recipe_with_its_dates(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Soup").mkdir(parents=True)
    (source / "Soup" / "recipe.md").write_text(
        "---\nscheduledOn:\n  - '2026-11-15'\n  - '2026-11-22'\n---\n# Soup\n",
        encoding="utf-8",
    )
    (source / "Stew").mkdir()
    (source / "Stew" / "recipe.md").write_text("---\n---\n# Stew\n", encoding="utf-8")

    entries = read_schedules(source)

    assert [entry["path"] for entry in entries] == ["Soup/recipe.md", "Stew/recipe.md"]
    assert entries[0]["title"] == "Soup"
    assert entries[0]["dates"] == ["2026-11-15", "2026-11-22"]
    assert entries[0]["url"] == "/Soup/recipe.html"
    # A recipe without a schedule is still listed, so it can be scheduled.
    assert entries[1]["dates"] == []


def test_read_schedules_finds_the_hero_image(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Soup").mkdir(parents=True)
    (source / "Soup" / "recipe.md").write_text("# Soup\n", encoding="utf-8")
    (source / "Soup" / "hero.png").write_bytes(b"")

    [entry] = read_schedules(source)

    assert entry["image"] == "/Soup/hero.png"


def test_write_dates_stores_the_dates_in_the_front_matter(tmp_path: Path):
    recipe = tmp_path / "recipe.md"
    recipe.write_text("---\ntitle: Soup\n---\n# Soup\n\nBody.\n", encoding="utf-8")

    assert write_dates(recipe, ["2026-11-22", "2026-11-15"]) == ["2026-11-15", "2026-11-22"]
    assert read_metadata(recipe)["scheduledOn"] == ["2026-11-15", "2026-11-22"]
    # The rest of the recipe is left alone.
    assert "# Soup" in recipe.read_text(encoding="utf-8")


def test_write_dates_removes_the_field_when_there_are_no_dates(tmp_path: Path):
    recipe = tmp_path / "recipe.md"
    recipe.write_text("---\nscheduledOn:\n  - '2026-11-15'\n---\n# Soup\n", encoding="utf-8")

    assert write_dates(recipe, []) == []
    assert "scheduledOn" not in read_metadata(recipe)


# ----- API ----- #


@pytest.fixture()
def scheduler_server(tmp_path: Path):
    source = tmp_path / "source"
    (source / "Soup").mkdir(parents=True)
    (source / "Soup" / "recipe.md").write_text("---\n---\n# Soup\n\nBody.\n", encoding="utf-8")

    with running_recipe_server(source) as (base_url, saved_paths, _):
        yield base_url, source, saved_paths


def test_scheduler_api_returns_the_schedule_of_every_recipe(scheduler_server):
    base_url, _, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler")

    assert status == 200
    assert [recipe["path"] for recipe in body["recipes"]] == ["Soup/recipe.md"]
    assert body["recipes"][0]["title"] == "Soup"


def test_scheduler_api_returns_the_accent_color_of_each_recipe(scheduler_server, tmp_path: Path):
    base_url, source, _ = scheduler_server
    write_png(source / "Soup" / "hero.png", (200, 70, 30))

    status, body = request_json(f"{base_url}/api/scheduler")

    assert status == 200
    color = body["recipes"][0]["color"]
    assert color.startswith("#")
    # The color comes from the hero image, so it is not the fallback.
    assert color.lower() != DEFAULT_FOOD_COLOR.lower()


def test_scheduler_api_falls_back_to_the_configured_color_without_a_hero_image(scheduler_server):
    base_url, _, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler")

    assert status == 200
    assert body["recipes"][0]["color"] == DEFAULT_FOOD_COLOR


def test_scheduler_api_saves_the_dates_to_the_front_matter(scheduler_server):
    base_url, source, saved_paths = scheduler_server

    status, body = request_json(
        f"{base_url}/api/scheduler",
        {"path": "Soup/recipe.md", "dates": ["2026-11-15", "2026-11-22"]},
    )

    assert status == 200
    assert body == {"success": True, "dates": ["2026-11-15", "2026-11-22"]}
    assert read_metadata(source / "Soup" / "recipe.md")["scheduledOn"] == ["2026-11-15", "2026-11-22"]
    # The recipe is regenerated so the index picks the new schedule up.
    assert saved_paths == [(source / "Soup" / "recipe.md").resolve()]


def test_scheduler_api_rejects_a_malformed_date(scheduler_server):
    base_url, source, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler", {"path": "Soup/recipe.md", "dates": ["soon"]})

    assert status == 400
    assert "Invalid scheduled date" in body["error"]
    assert "scheduledOn" not in read_metadata(source / "Soup" / "recipe.md")


def test_scheduler_api_rejects_a_path_outside_the_source_directory(scheduler_server):
    base_url, _, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler", {"path": "../outside.md", "dates": []})

    assert status == 400


def test_scheduler_api_rejects_a_missing_path(scheduler_server):
    base_url, _, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler", {"dates": []})

    assert status == 400
    assert body == {"error": "Expected string field: path"}


def test_scheduler_api_reports_a_missing_recipe(scheduler_server):
    base_url, _, _ = scheduler_server

    status, body = request_json(f"{base_url}/api/scheduler", {"path": "Nope/recipe.md", "dates": []})

    assert status == 404
    assert body == {"error": "Markdown file not found"}


def test_scheduler_api_can_clear_a_schedule(scheduler_server):
    base_url, source, _ = scheduler_server

    request_json(f"{base_url}/api/scheduler", {"path": "Soup/recipe.md", "dates": ["2026-11-15"]})
    status, body = request_json(f"{base_url}/api/scheduler", {"path": "Soup/recipe.md", "dates": []})

    assert status == 200
    assert body == {"success": True, "dates": []}
    assert "scheduledOn" not in read_metadata(source / "Soup" / "recipe.md")


# ----- Index page ----- #


def build_index(tmp_path: Path) -> BeautifulSoup:
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({}, recipe_path))
    generator.convert()

    return BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")


def test_index_renders_a_scheduler_button_next_to_the_shopping_list(tmp_path: Path):
    soup = build_index(tmp_path)

    button_ids = [button["id"] for button in soup.select("#bulk-controls button")]
    assert "scheduler" in button_ids
    assert button_ids.index("shopping-list") < button_ids.index("scheduler")


def test_the_scheduler_button_is_a_selection_action_with_an_icon(tmp_path: Path):
    soup = build_index(tmp_path)

    button = soup.select_one("#scheduler")
    # The button schedules the selected recipes, so it belongs to the
    # selection actions and stays hidden outside selection mode.
    assert button.get("data-selection-only") is not None
    assert button.get("hidden") is not None
    assert button.get("disabled") is not None
    assert button.get_text(strip=True) == "Schedule Selected"

    icon = button.find("svg")
    assert icon is not None
    assert "lucide-calendar" in icon.get("class", [])


def test_index_loads_the_scheduler_assets(tmp_path: Path):
    soup = build_index(tmp_path)

    hrefs = [link["href"] for link in soup.select('link[rel="stylesheet"]')]
    assert any(href.startswith("/assets/scheduler/scheduler.css") for href in hrefs)

    sources = [script["src"] for script in soup.select("script[src]")]
    assert any(src.startswith("/assets/scheduler/scheduler.js") for src in sources)


# ----- Assets ----- #


def test_the_scheduler_assets_exist():
    assert (SCHEDULER_ASSETS / "scheduler.html").is_file()
    assert (SCHEDULER_ASSETS / "scheduler.css").is_file()
    assert (SCHEDULER_ASSETS / "scheduler.js").is_file()


def test_the_scheduler_offers_the_three_views():
    html = (SCHEDULER_ASSETS / "scheduler.html").read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    views = [button["data-scheduler-view"] for button in soup.select("[data-scheduler-view]")]
    assert views == ["day", "week", "month"]


def test_the_scheduler_has_a_selection_count_and_no_snap_control():
    html = (SCHEDULER_ASSETS / "scheduler.html").read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one(".scheduler__selection") is not None
    # There is no snap control anywhere.
    assert soup.select_one(".scheduler__snap-slider") is None
    assert soup.select_one(".scheduler__snap") is None
    # The recipe picker is gone; the count takes its place.
    assert soup.select_one(".scheduler__recipe") is None


def test_the_scheduler_scrolls_without_snapping():
    css = (SCHEDULER_ASSETS / "scheduler.css").read_text(encoding="utf-8")
    script = (SCHEDULER_ASSETS / "scheduler.js").read_text(encoding="utf-8")

    # Every view scrolls in the one calendar container. A page grows to
    # show all of its recipes instead of becoming a nested scroller.
    assert "overflow-y: auto" in css
    assert ".scheduler__month-week" in css
    assert "flex: 1 0 auto" in css
    assert "overflow-y: auto" not in css.split(".scheduler__page-body", 1)[1]

    # The snap strength and its glide are gone.
    assert "--scheduler-snap-strength" not in css
    assert "snapStrength" not in script
    assert "glideTo" not in script


def test_the_scheduler_toolbar_has_today_and_select_without_arrows():
    html = (SCHEDULER_ASSETS / "scheduler.html").read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    toolbar = soup.select_one(".scheduler__toolbar")
    assert toolbar.select_one(".scheduler__today") is not None
    assert toolbar.select_one(".scheduler__select") is not None
    # The calendar scrolls, so there are no previous/next arrows.
    assert soup.select_one(".scheduler__nav") is None
    assert soup.select_one("[data-scheduler-step]") is None


def test_the_scheduler_has_a_frozen_weekday_row_for_the_month_view():
    html = (SCHEDULER_ASSETS / "scheduler.html").read_text(encoding="utf-8")
    css = (SCHEDULER_ASSETS / "scheduler.css").read_text(encoding="utf-8")
    script = (SCHEDULER_ASSETS / "scheduler.js").read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    scroll = soup.select_one(".scheduler__scroll")
    weekdays = scroll.select_one(".scheduler__weekdays")
    # The row is the first child of the one scroll container, so it can
    # stay put while the months scroll beneath it.
    assert weekdays is scroll.find(recursive=False)
    assert weekdays.has_attr("hidden")
    assert len(weekdays.select("span")) == 7

    assert "position: sticky" in css
    assert ".scheduler__weekdays[hidden]" in css
    assert 'state.weekdays.hidden = view !== "month"' in script


def test_the_scheduler_shows_the_shopping_list_only_in_selection_mode():
    html = (SCHEDULER_ASSETS / "scheduler.html").read_text(encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")
    footer = soup.select_one(".scheduler__footer")
    shopping = footer.select_one(".scheduler__shopping")

    assert shopping is not None
    assert shopping.get_text(strip=True) == "Open in Shopping List"
    assert shopping.has_attr("hidden")
    assert shopping.select_one(".scheduler__icon") is not None

    script = (SCHEDULER_ASSETS / "scheduler.js").read_text(encoding="utf-8")
    assert '"/assets/shopping-cart.svg"' in script
    assert "new CustomEvent(SHOPPING_LIST_EVENT, { detail: { paths } })" in script
    assert 'state.shoppingButton.hidden = state.mode !== "day"' in script


def test_a_click_in_selection_mode_picks_the_day_even_on_a_recipe():
    script = (SCHEDULER_ASSETS / "scheduler.js").read_text(encoding="utf-8")

    entry = script.split("function buildEntry", 1)[1].split("return entry;", 1)[0]
    # In selection mode the entry stops the link and picks the day.
    assert "event.preventDefault();" in entry
    assert "toggleDay(dateText);" in entry
    # Otherwise a recipe link opens its page.
    assert 'event.target.closest("a, button")' in entry


def test_pull_to_refresh_is_disabled_while_the_scheduler_is_open():
    script = (ASSETS / "pull-down-page-refresh.js").read_text(encoding="utf-8")

    assert 'document.getElementById("scheduler-dialog")' in script


def test_the_scheduler_script_talks_to_the_scheduler_api():
    script = (SCHEDULER_ASSETS / "scheduler.js").read_text(encoding="utf-8")

    assert '"/api/scheduler"' in script
    assert "scheduledOn" not in script
