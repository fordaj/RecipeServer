"""End-to-end coverage for the name dropdowns in the feedback forms."""

import json
from urllib.request import Request, urlopen

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from test.e2e.helpers import open_page, wait_clickable, wait_visible


def _wait_for_option(driver, css: str, value: str, timeout: int = 10) -> None:
    WebDriverWait(driver, timeout).until(lambda d: value in [o.text for o in Select(d.find_element(By.CSS_SELECTOR, css)).options])


def _post_comment(url, path, author, text, comment_id):
    payload = json.dumps(
        {
            "path": path,
            "value": [
                {
                    "id": comment_id,
                    "author": author,
                    "text": text,
                    "created": "2026-01-01T00:00:00.000Z",
                    "updated": "2026-01-01T00:00:00.000Z",
                }
            ],
        }
    ).encode("utf-8")
    request = Request(
        f"{url}/api/metadata/comments",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        assert response.status == 200


def _post_rating(url, path, name, rating=8):
    payload = json.dumps(
        {
            "path": path,
            "value": [
                {
                    "name": name,
                    "rating": rating,
                    "id": f"e2e-{name}",
                    "created": "2026-01-01T00:00:00.000Z",
                    "updated": "2026-01-01T00:00:00.000Z",
                }
            ],
        }
    ).encode("utf-8")
    request = Request(
        f"{url}/api/metadata/ratings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        assert response.status == 200


def test_name_dropdowns_offer_library_names_and_remember_the_device(driver, recipe_server):
    _post_rating(recipe_server.url, "cake/recipe.md", "Avery")

    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "#recipe-ratings")

    # The add-form name dropdown offers the library's raters. The options
    # are re-read when the form opens.
    wait_clickable(driver, ".recipe-ratings__add").click()
    _wait_for_option(driver, "#recipe-rating-form .recipe-editor__picker-select", "Avery (1)")
    select = Select(driver.find_element("css selector", "#recipe-rating-form .recipe-editor__picker-select"))
    option_texts = [option.text for option in select.options]
    assert "Avery (1)" in option_texts

    # "Add new…" swaps the dropdown for a text field.
    select.select_by_value("__new__")
    new_input = driver.find_element("css selector", "#recipe-rating-form .recipe-editor__picker-new")
    assert new_input.is_displayed()
    new_input.send_keys("Kailey")
    driver.find_element("css selector", "#recipe-rating-form .recipe-editor__picker-add").click()
    chip = wait_visible(driver, "#recipe-rating-form .recipe-editor__picker-chip")
    assert chip.text.startswith("Kailey")

    # Post the rating; the device remembers the name.
    wait_clickable(driver, "#save-rating").click()
    wait_visible(driver, ".recipe-rating__author")
    assert driver.execute_script("return window.localStorage.getItem('lastRater');") == "Kailey"

    # Reload the page; the remembered name is preselected. Opening the form
    # re-renders the picker once the library names arrive, so read the chip
    # atomically instead of holding an element reference across the fetch.
    driver.refresh()
    wait_visible(driver, "#recipe-ratings")
    wait_clickable(driver, ".recipe-ratings__add").click()
    _wait_for_option(driver, "#recipe-rating-form .recipe-editor__picker-select", "Avery (1)")
    chip_text = driver.execute_script("return document.querySelector('#recipe-rating-form .recipe-editor__picker-chip')?.textContent ?? '';")
    assert chip_text.startswith("Kailey")


def test_comment_name_dropdown_remembers_the_device(driver, recipe_server):
    # Someone else commenting elsewhere in the library is an option.
    _post_comment(recipe_server.url, "cake/recipe.md", "Avery", "Nice.", "e2e-avery")

    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "#recipe-comments")

    # The options are re-read when the form opens.
    wait_clickable(driver, ".recipe-comments__add").click()
    _wait_for_option(driver, "#recipe-comment-form .recipe-editor__picker-select", "Avery (1)")
    select = Select(driver.find_element("css selector", "#recipe-comment-form .recipe-editor__picker-select"))
    select.select_by_value("__new__")
    new_input = driver.find_element("css selector", "#recipe-comment-form .recipe-editor__picker-new")
    assert new_input.is_displayed()
    new_input.send_keys("Kailey")
    driver.find_element("css selector", "#recipe-comment-form .recipe-editor__picker-add").click()

    text = driver.find_element("css selector", "#comment-text")
    text.send_keys("Tasted great.")
    wait_clickable(driver, "#save-comment").click()
    wait_visible(driver, ".recipe-comment__author")
    assert driver.execute_script("return window.localStorage.getItem('lastCommenter');") == "Kailey"

    # The remembered name comes back preselected; the library names are
    # re-read when the form opens again. Kailey is already selected, so it
    # is not re-offered (single-value pickers hide the selected value).
    driver.refresh()
    wait_visible(driver, "#recipe-comments")
    wait_clickable(driver, ".recipe-comments__add").click()
    _wait_for_option(driver, "#recipe-comment-form .recipe-editor__picker-select", "Avery (1)")
    chip_text = driver.execute_script("return document.querySelector('#recipe-comment-form .recipe-editor__picker-chip')?.textContent ?? '';")
    assert chip_text.startswith("Kailey")
