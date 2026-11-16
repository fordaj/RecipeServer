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

    # The add-form name field carries the remembered/typed name in its text
    # input; the dropdown offers the library's raters. The options are
    # re-read when the form opens.
    wait_clickable(driver, ".recipe-ratings__add").click()
    _wait_for_option(driver, "#recipe-rating-form .recipe-editor__picker-select", "Avery (1)")
    name_input = driver.find_element("css selector", "#recipe-rating-form .recipe-editor__picker-input")
    assert name_input.get_attribute("value") == ""
    # Picking a library name writes it into the input; no chip is rendered.
    select = Select(driver.find_element("css selector", "#recipe-rating-form .recipe-editor__picker-select"))
    select.select_by_visible_text("Avery (1)")
    assert name_input.get_attribute("value") == "Avery"
    assert driver.execute_script("return document.querySelector('#recipe-rating-form .recipe-editor__picker-chip') !== null;") is False

    # Type a name that is not in the library and post the rating.
    name_input.clear()
    name_input.send_keys("Kailey")

    # Post the rating; the device remembers the name.
    wait_clickable(driver, "#save-rating").click()
    wait_visible(driver, ".recipe-rating__author")
    assert driver.execute_script("return window.localStorage.getItem('lastRater');") == "Kailey"

    # Reload the page; the remembered name is prefilled in the text input.
    # Opening the form re-reads the library name, so read the input after the
    # options arrive.
    driver.refresh()
    wait_visible(driver, "#recipe-ratings")
    wait_clickable(driver, ".recipe-ratings__add").click()
    _wait_for_option(driver, "#recipe-rating-form .recipe-editor__picker-select", "Avery (1)")
    value = driver.execute_script("return document.querySelector('#recipe-rating-form .recipe-editor__picker-input')?.value ?? '';")
    assert value == "Kailey"


def test_comment_name_dropdown_remembers_the_device(driver, recipe_server):
    # Someone else commenting elsewhere in the library is an option.
    _post_comment(recipe_server.url, "cake/recipe.md", "Avery", "Nice.", "e2e-avery")

    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_visible(driver, "#recipe-comments")

    # The options are re-read when the form opens. Type a name that is not
    # in the library into the text input.
    wait_clickable(driver, ".recipe-comments__add").click()
    _wait_for_option(driver, "#recipe-comment-form .recipe-editor__picker-select", "Avery (1)")
    name_input = driver.find_element("css selector", "#recipe-comment-form .recipe-editor__picker-input")
    assert name_input.get_attribute("value") == ""
    name_input.send_keys("Kailey")

    text = driver.find_element("css selector", "#comment-text")
    text.send_keys("Tasted great.")
    wait_clickable(driver, "#save-comment").click()
    wait_visible(driver, ".recipe-comment__author")
    assert driver.execute_script("return window.localStorage.getItem('lastCommenter');") == "Kailey"

    # The remembered name comes back prefilled in the text input; the
    # library names are re-read when the form opens again.
    driver.refresh()
    wait_visible(driver, "#recipe-comments")
    wait_clickable(driver, ".recipe-comments__add").click()
    _wait_for_option(driver, "#recipe-comment-form .recipe-editor__picker-select", "Avery (1)")
    value = driver.execute_script("return document.querySelector('#recipe-comment-form .recipe-editor__picker-input')?.value ?? '';")
    assert value == "Kailey"
