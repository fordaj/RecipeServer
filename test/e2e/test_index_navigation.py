"""End-to-end coverage for the index: listings, search, and navigation."""

from test.e2e.helpers import open_page, visible_recipe_titles, wait_visible


def test_recipe_listings_render(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    assert sorted(visible_recipe_titles(driver)) == ["Chocolate Cake", "Sample"]


def test_search_filters_recipe_listings(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    search = driver.find_element("css selector", '[data-testid="recipe-search"]')
    search.send_keys("chocolate")

    wait_visible(driver, 'li[data-testid="recipe-item"][data-title="Chocolate Cake"]:not([hidden])')
    assert visible_recipe_titles(driver) == ["Chocolate Cake"]


def test_open_recipe_from_index_and_navigate_back(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    link = driver.find_element("css selector", 'li[data-title="Sample"] .recipe-card__link')
    link.click()

    heading = wait_visible(driver, "h1")
    assert heading.text == "Sample"
    assert driver.current_url.endswith("/waffles/recipe.html")

    driver.find_element("css selector", "a.recipe-home").click()
    wait_visible(driver, 'li[data-testid="recipe-item"]')
    assert driver.current_url.endswith("/index.html")


def test_recipe_metadata_renders(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, ".recipe-meta")

    meta = driver.find_element("css selector", ".recipe-meta")
    assert "time" in meta.text.lower()
    assert "20 minutes" in meta.text
    overview = driver.find_element("css selector", ".recipe-overview")
    assert "Breakfast" in overview.text
