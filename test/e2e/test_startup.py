"""End-to-end coverage for application startup and static assets."""

import json
from urllib.request import urlopen

from test.e2e.helpers import open_page, severe_console_errors, wait_visible


def test_server_starts_and_reports_healthy(recipe_server):
    with urlopen(f"{recipe_server.url}/health", timeout=10) as response:
        assert response.status == 200
        assert json.loads(response.read())["status"] == "ok"


def test_homepage_loads_and_lists_recipes(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")

    heading = wait_visible(driver, ".recipes-header h1")
    assert heading.text == "My Recipe Server"
    wait_visible(driver, 'li[data-testid="recipe-item"]')


def test_static_assets_load_and_images_render(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "h1")

    hero = driver.find_element("css selector", 'main img[alt="Sample"]')
    loaded = driver.execute_script("return arguments[0].complete && arguments[0].naturalWidth > 0;", hero)
    assert loaded, "hero image did not load"


def test_no_severe_browser_errors_on_index_or_recipe(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "h1")

    assert severe_console_errors(driver) == []
