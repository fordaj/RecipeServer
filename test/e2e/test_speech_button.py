"""End-to-end coverage for the dictation button on the index page.

The end-to-end server speaks plain HTTP, so the button must not be offered:
the browser only hands out the microphone to pages served over HTTPS, and
the feature is hidden everywhere else.
"""

from selenium.webdriver.common.by import By

from test.e2e.helpers import open_page, severe_console_errors, visible_recipe_titles, wait_visible


def test_dictation_button_is_not_offered_without_https(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    buttons = driver.find_elements(By.CSS_SELECTOR, '[data-testid="speech-button"]')

    assert all(not button.is_displayed() for button in buttons), "the dictation button is only offered over HTTPS"


def test_search_still_works_with_the_dictation_wrapper(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    search = driver.find_element("css selector", '[data-testid="recipe-search"]')
    search.send_keys("chocolate")

    wait_visible(driver, 'li[data-testid="recipe-item"][data-title="Chocolate Cake"]:not([hidden])')
    assert visible_recipe_titles(driver) == ["Chocolate Cake"]


def test_index_page_serves_the_dictation_assets(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_visible(driver, 'li[data-testid="recipe-item"]')

    for path in ("/assets/speech-button/speech-button.js", "/assets/speech-button/speech-button.css"):
        assert driver.execute_script("return fetch(arguments[0]).then((r) => r.status)", path) == 200

    assert severe_console_errors(driver) == []
