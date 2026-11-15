"""End-to-end coverage for interactive recipe page behavior."""

from selenium.webdriver.support.ui import Select

from test.e2e.helpers import open_page, wait_clickable, wait_visible

TWO_CUP_QUANTITY = '.quantity[data-quantity="2.0"][data-unit="cup"]'


def test_ingredient_checkbox_can_be_toggled(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, ".task-list input[type='checkbox']")

    checkbox = driver.find_element("css selector", ".task-list input[type='checkbox']")
    assert not checkbox.is_selected()

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", checkbox)
    wait_clickable(driver, ".task-list input[type='checkbox']").click()
    assert checkbox.is_selected()

    wait_clickable(driver, ".task-list input[type='checkbox']").click()
    assert not checkbox.is_selected()


def test_recipe_scaling_updates_ingredient_quantities(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, TWO_CUP_QUANTITY)

    quantity = driver.find_element("css selector", TWO_CUP_QUANTITY)
    assert quantity.get_attribute("data-scaled-quantity") == "2"

    scaler = Select(driver.find_element("css selector", ".recipe-scale-select"))
    scaler.select_by_value("2")

    wait_visible(driver, TWO_CUP_QUANTITY)
    assert driver.find_element("css selector", TWO_CUP_QUANTITY).get_attribute("data-scaled-quantity") == "4"
    assert driver.find_element("css selector", TWO_CUP_QUANTITY).get_attribute("data-scaled-text").startswith("4")


def test_recipe_custom_scale_updates_quantities(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, TWO_CUP_QUANTITY)

    Select(driver.find_element("css selector", ".recipe-scale-select")).select_by_value("custom")

    custom_input = wait_visible(driver, ".recipe-scale-custom")
    custom_input.clear()
    custom_input.send_keys("0.5")

    assert driver.find_element("css selector", TWO_CUP_QUANTITY).get_attribute("data-scaled-quantity") == "1"


def test_recipe_image_renders(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "h1")

    image = driver.find_element("css selector", 'main img[alt="Sample"]')
    loaded = driver.execute_script("return arguments[0].complete && arguments[0].naturalWidth > 0;", image)
    assert loaded
