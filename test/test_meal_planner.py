"""Tests for the meal planner: ingredient scraping, its API, and its assets."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest
from bs4 import BeautifulSoup

from recipeserver.meal_planner import parse_ingredient, scrape_ingredients
from recipeserver.index_html_generator import IndexHTMLGenerator, Recipe

from types import SimpleNamespace

ASSETS = Path(__file__).parents[1] / "src" / "recipeserver" / "assets"
MEAL_PLANNER_ASSETS = ASSETS / "meal-planner"

RECIPE_PAGE = """
<html>
  <body>
    <main class="recipe">
      <h1>Soup</h1>
      <h2>Ingredients</h2>
      <ul class="task-list">
        <li class="task-list-item"><input type="checkbox"/> <span class="quantity" data-quantity="0.5" data-unit="cup"></span> of flour</li>
        <li class="task-list-item"><input type="checkbox"/> salt to taste</li>
      </ul>
      <h2>Preparation</h2>
      <ol><li>Mix everything.</li></ol>
      <h2>Tips</h2>
      <ul><li>Stir well.</li></ul>
    </main>
  </body>
</html>
"""


# ----- Ingredient scraping ----- #


def test_scrape_ingredients_collects_items_under_an_ingredient_heading():
    ingredients = scrape_ingredients(RECIPE_PAGE)

    assert len(ingredients) == 2
    assert "of flour" in ingredients[0]["html"]
    assert "salt to taste" in ingredients[1]["html"]


def test_scrape_ingredients_keeps_the_quantity_spans():
    [ingredient] = scrape_ingredients(RECIPE_PAGE)[:1]

    assert 'class="quantity"' in ingredient["html"]
    assert 'data-quantity="0.5"' in ingredient["html"]
    assert 'data-unit="cup"' in ingredient["html"]


def test_scrape_ingredients_stops_at_the_next_heading():
    ingredients = scrape_ingredients(RECIPE_PAGE)

    assert not any("Stir well" in ingredient["html"] for ingredient in ingredients)


def test_scrape_ingredients_matches_the_heading_case_insensitively():
    html = "<h2>INGREDIENTS</h2><ul><li>salt</li></ul><h2>Other</h2><ul><li>pepper</li></ul>"

    assert [ingredient["html"] for ingredient in scrape_ingredients(html)] == ["salt"]


def test_scrape_ingredients_requires_an_ingredient_heading():
    html = "<h1>Soup</h1><ul><li>water</li></ul>"

    assert scrape_ingredients(html) == []


def test_scrape_ingredients_re_evaluates_the_heading_for_every_section():
    html = """
      <h2>Ingredients</h2><ul><li>flour</li></ul>
      <h2>Method</h2><ul><li>mix</li></ul>
      <h2>More Ingredients</h2><ul><li>salt</li></ul>
    """

    assert [ingredient["html"] for ingredient in scrape_ingredients(html)] == ["flour", "salt"]


def test_scrape_ingredients_reads_nested_list_items():
    html = "<h2>Ingredients</h2><ul><li>flour<ul><li>more flour</li></ul></li></ul>"

    assert [ingredient["html"] for ingredient in scrape_ingredients(html)] == [
        "flour<ul><li>more flour</li></ul>",
        "more flour",
    ]


# ----- Combining ingredients ----- #


def test_parse_ingredient_names_the_ingredient_without_the_amount():
    ingredient = parse_ingredient('<span class="quantity" data-quantity="0.5" data-unit="cup"></span> of flour')

    assert ingredient["name"] == "flour"
    assert ingredient["unit"] == "cup"
    assert ingredient["has_range"] is False


def test_parse_ingredient_ignores_a_leading_of():
    assert parse_ingredient("<span class='quantity'></span> of flour")["name"] == "flour"
    assert parse_ingredient("flour")["name"] == "flour"


def test_parse_ingredient_normalizes_the_plural_of_a_unit():
    assert parse_ingredient('<span class="quantity" data-unit="cups"></span> flour')["unit"] == "cup"
    assert parse_ingredient('<span class="quantity" data-unit="carrots"></span>')["unit"] == "carrot"


def test_parse_ingredient_keeps_units_that_end_in_es_or_ss():
    assert parse_ingredient('<span class="quantity" data-unit="molasses"></span>')["unit"] == "molasses"
    assert parse_ingredient('<span class="quantity" data-unit="tomatoes"></span>')["unit"] == "tomatoes"


def test_parse_ingredient_notices_a_range():
    range_ingredient = parse_ingredient('<span class="quantity" data-quantity="2" data-quantity-end="3" data-unit="cup"></span> stock')
    plain_ingredient = parse_ingredient('<span class="quantity" data-quantity="2" data-unit="cup"></span> stock')

    assert range_ingredient["has_range"] is True
    assert plain_ingredient["has_range"] is False


def test_parse_ingredient_keeps_the_ingredient_without_an_amount():
    ingredient = parse_ingredient("salt to taste")

    assert ingredient["name"] == "salt to taste"
    assert ingredient["unit"] == ""
    assert ingredient["has_range"] is False


# ----- API ----- #


@pytest.fixture()
def meal_planner_server(tmp_path):
    from functools import partial
    from http.server import ThreadingHTTPServer
    from threading import Thread

    from recipeserver.server import RecipeRequestHandler

    source = tmp_path / "source"
    site = tmp_path / "site"
    (source / "Soup").mkdir(parents=True)
    (source / "Soup" / "recipe.md").write_text("---\n---\n# Soup\n", encoding="utf-8")
    (site / "Soup").mkdir(parents=True)
    (site / "Soup" / "recipe.html").write_text(RECIPE_PAGE, encoding="utf-8")

    handler = partial(RecipeRequestHandler, directory=str(site), source_directory=source)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_meal_planner_api_returns_the_ingredients_of_each_recipe(meal_planner_server):
    query = urlencode({"path": ["Soup/recipe.md"]}, doseq=True)

    with urlopen(f"{meal_planner_server}/api/meal-planner?{query}") as response:
        data = json.loads(response.read())

    assert [recipe["path"] for recipe in data["recipes"]] == ["Soup/recipe.md"]
    assert len(data["recipes"][0]["ingredients"]) == 2
    assert "of flour" in data["recipes"][0]["ingredients"][0]["html"]
    # The name and the unit say which ingredient this is, so the planner can
    # add the amounts of several recipes together.
    assert data["recipes"][0]["ingredients"][0]["name"] == "flour"
    assert data["recipes"][0]["ingredients"][0]["unit"] == "cup"


def test_meal_planner_api_rejects_paths_outside_the_source_directory(meal_planner_server):
    query = urlencode({"path": ["../outside.md"]}, doseq=True)

    with pytest.raises(HTTPError) as error:
        urlopen(f"{meal_planner_server}/api/meal-planner?{query}")

    assert error.value.code == 400


def test_meal_planner_api_reports_a_missing_recipe_page(meal_planner_server, tmp_path):
    (tmp_path / "source" / "Stew").mkdir()
    (tmp_path / "source" / "Stew" / "recipe.md").write_text("---\n---\n# Stew\n", encoding="utf-8")
    query = urlencode({"path": ["Stew/recipe.md"]}, doseq=True)

    with pytest.raises(HTTPError) as error:
        urlopen(f"{meal_planner_server}/api/meal-planner?{query}")

    assert error.value.code == 404


def test_meal_planner_api_requires_at_least_one_recipe(meal_planner_server):
    with pytest.raises(HTTPError) as error:
        urlopen(f"{meal_planner_server}/api/meal-planner")

    assert error.value.code == 400


# ----- Index page ----- #


def test_index_renders_a_plan_meals_button_next_to_bulk_edit(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({"categories": ["Soup"]}, recipe_path))
    generator.convert()

    soup = BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")

    button_ids = [button["id"] for button in soup.select("#bulk-controls button")]
    assert button_ids == ["clear-selections", "bulk-delete", "bulk-edit", "plan-meals"]

    plan_meals = soup.select_one("#plan-meals")
    assert plan_meals.get_text(strip=True) == "Plan Meals"
    assert plan_meals["disabled"] is not None


def test_index_loads_the_meal_planner_assets(tmp_path: Path):
    recipe_path = tmp_path / "soup" / "recipe.html"
    recipe_path.parent.mkdir()
    recipe_path.write_text("<h1>Soup</h1>", encoding="utf-8")

    generator = IndexHTMLGenerator(SimpleNamespace(site_directory=tmp_path))
    generator.add(Recipe({}, recipe_path))
    generator.convert()

    soup = BeautifulSoup((tmp_path / "index.html").read_text(encoding="UTF-8"), "html.parser")

    stylesheets = [link["href"] for link in soup.select('link[rel="stylesheet"]')]
    scripts = [script["src"] for script in soup.select("script[src]")]

    # The asset URLs carry a content hash, so match on the path.
    assert any("/assets/meal-planner/meal-planner.css" in href for href in stylesheets)
    assert any("/assets/meal-planner/meal-planner.js" in src for src in scripts)
    # The meal planner reuses the recipe scaler, so the page needs it too.
    assert any("/assets/recipe-scaler.css" in href for href in stylesheets)
    assert any("/assets/recipe-scaler.js" in src for src in scripts)


def test_index_js_dispatches_the_plan_meals_event():
    index_js = (ASSETS / "index.js").read_text(encoding="UTF-8")

    assert 'document.querySelector("#plan-meals")' in index_js
    assert 'new CustomEvent("plan-meals", { detail: { paths } })' in index_js


# ----- Meal planner assets ----- #


def test_meal_planner_template_has_the_combined_ingredients_checklist():
    markup = (MEAL_PLANNER_ASSETS / "meal-planner.html").read_text(encoding="UTF-8")
    soup = BeautifulSoup(markup, "html.parser")

    heading = soup.select_one(".meal-planner__combined h3")
    assert heading is not None
    assert heading.get_text(strip=True) == "Combined Ingredients"

    checklist = soup.select_one(".meal-planner__combined ul")
    assert checklist is not None
    assert "task-list" in checklist.get("class")

    done = soup.select_one(".meal-planner__done")
    assert done is not None
    assert done.get_text(strip=True) == "Done"


def test_meal_planner_styles_the_done_button_like_the_save_button():
    css = (MEAL_PLANNER_ASSETS / "meal-planner.css").read_text(encoding="UTF-8")

    done_rule = css.split(".meal-planner__footer .meal-planner__done {")[1].split("}")[0]
    assert "background: var(--food-color)" in done_rule
    assert "color: var(--page-bg)" in done_rule


def test_meal_planner_lays_the_recipes_out_as_a_grid_of_rows():
    css = (MEAL_PLANNER_ASSETS / "meal-planner.css").read_text(encoding="UTF-8")

    assert ".meal-planner__recipe {" in css
    assert "display: grid" in css
    assert "grid-template-columns: auto auto minmax(0, 1fr)" in css


def test_meal_planner_scales_each_recipe_on_its_own():
    script = (MEAL_PLANNER_ASSETS / "meal-planner.js").read_text(encoding="UTF-8")

    # One scaler per recipe row, each scoped to that row.
    assert "new RecipeScaler(row, { onUpdate: renderCombined })" in script
    assert "RECIPE_SCALER_URL" in script


def test_meal_planner_sorts_the_combined_ingredients_alphabetically():
    script = (MEAL_PLANNER_ASSETS / "meal-planner.js").read_text(encoding="UTF-8")

    assert "localeCompare" in script
    assert "task-list-item" in script


def test_meal_planner_adds_the_amounts_of_the_same_ingredient_together():
    script = (MEAL_PLANNER_ASSETS / "meal-planner.js").read_text(encoding="UTF-8")

    # Ingredients are grouped by the key the server works out, and the
    # amounts of the group are added together.
    assert "function mergeEntries(" in script
    assert "group.quantity += entry.quantity" in script
    assert "group.end += entry.end" in script
    assert "mergeKeyFor" in script


def test_meal_planner_shows_the_recipes_the_ingredients_come_from():
    script = (MEAL_PLANNER_ASSETS / "meal-planner.js").read_text(encoding="UTF-8")
    css = (MEAL_PLANNER_ASSETS / "meal-planner.css").read_text(encoding="UTF-8")

    assert "meal-planner__sources" in script
    assert "group.sources.join" in script
    # The sources sit to the right of the checkbox, in muted italic text.
    assert ".meal-planner__sources {" in css
    assert "font-style: italic" in css
    assert "color: var(--muted-color)" in css
    assert "margin-left: auto" in css


def test_meal_planner_names_the_recipes_in_the_food_color():
    css = (MEAL_PLANNER_ASSETS / "meal-planner.css").read_text(encoding="UTF-8")

    name_rule = css.split(".meal-planner__name {")[1].split("}")[0]
    assert "color: var(--food-color)" in name_rule


def test_meal_planner_prints_the_checklist_in_two_columns():
    css = (MEAL_PLANNER_ASSETS / "meal-planner.css").read_text(encoding="UTF-8")

    print_rule = css.split("@media print {")[1]
    assert "columns: 2" in print_rule
    assert "break-inside: avoid" in print_rule
