"""End-to-end coverage for the Version History (Timeline) dialog.

The dialog opens from the recipe page's sandwich menu (the data-timeline
entry); the tests exercise that real path rather than the
``window.RecipeTimeline`` hook directly.
"""

import json
from urllib.request import Request, urlopen

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from test.e2e.helpers import open_page, wait_clickable, wait_hidden, wait_text, wait_visible

RECIPE_PAGE = "/waffles/recipe.html"
RECIPE_API_PATH = "waffles/recipe.md"


def _post_json(url, payload, method="POST"):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(request) as response:
        return response.status, json.loads(response.read())


def _markdown(url):
    with urlopen(f"{url}/api/markdown?path={RECIPE_API_PATH}") as response:
        return response.read().decode("utf-8")


def _make_edit(url, body):
    status, _ = _post_json(f"{url}/api/markdown", {"path": RECIPE_API_PATH, "content": body})
    assert status == 200


def _open_timeline(driver):
    wait_clickable(driver, ".sandwich-menu__toggle").click()
    wait_visible(driver, ".sandwich-menu__panel:not([hidden])")
    wait_clickable(driver, '.sandwich-menu__item[data-timeline="open"]').click()
    wait_visible(driver, ".recipe-history-dialog[open]")
    # The menu closes behind the dialog, like the Edit Recipe entry does.
    wait_hidden(driver, ".sandwich-menu__panel")


def test_timeline_opens_and_lists_versions(driver, recipe_server):
    _make_edit(recipe_server.url, "# Sample\n\nVersion two.\n")
    open_page(driver, f"{recipe_server.url}{RECIPE_PAGE}")
    wait_visible(driver, "h1")

    _open_timeline(driver)

    wait_visible(driver, ".recipe-history__current-badge")
    # One snapshot exists, so the timeline shows the current badge plus one snapshot entry.
    entries = driver.find_elements(By.CSS_SELECTOR, ".recipe-history__entry")
    assert len(entries) == 2
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-history__entry--current")
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-history__date")
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-history__entry:not(.recipe-history__entry--current) .recipe-history__item")


def test_timeline_preview_compare_and_restore(driver, recipe_server):
    _make_edit(recipe_server.url, "# Sample\n\nVersion two.\n")

    open_page(driver, f"{recipe_server.url}{RECIPE_PAGE}")
    wait_visible(driver, "h1")
    _open_timeline(driver)

    # Select the previous version; the preview frame points at the preview endpoint.
    snapshot_button = wait_visible(
        driver,
        ".recipe-history__entry:not(.recipe-history__entry--current) .recipe-history__item",
    )
    snapshot_button.click()
    frame = driver.find_element(By.CSS_SELECTOR, ".recipe-history__preview")
    assert "/api/history/preview" in frame.get_attribute("src")

    # Compare renders a diff against the current recipe.
    driver.find_element(By.CSS_SELECTOR, '.recipe-history__mode[data-mode="compare"]').click()
    wait_visible(driver, ".recipe-history__diff:not([hidden])")
    # The diff is filled asynchronously from /api/history/compare; waiting only
    # for visibility can read an empty element on a busy full-suite run.
    wait_text(driver, ".recipe-history__diff", "+Version two.", 20)
    diff_text = driver.find_element(By.CSS_SELECTOR, ".recipe-history__diff").text
    assert "+Version two." in diff_text

    # Restore is a two-step confirm; confirming reloads the page with the restored recipe.
    restore = wait_clickable(driver, ".recipe-history__restore", 20)
    restore.click()
    # The first click arms a two-step confirm, which can re-render the button.
    wait_text(driver, ".recipe-history__restore", "Confirm restore", 20)
    wait_clickable(driver, ".recipe-history__restore", 20).click()

    # Restoring triggers a page reload; under a busy full-suite run that reload
    # can take longer than the default ten seconds. Wait for the document to
    # finish loading before asserting the restored body.
    WebDriverWait(driver, 25).until(lambda d: d.execute_script("return document.readyState") == "complete")
    WebDriverWait(
        driver,
        25,
        ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
    ).until(lambda d: "Version two" not in d.find_element(By.CSS_SELECTOR, "main").text)
    assert "Version two" not in _markdown(recipe_server.url)


def test_timeline_empty_state_when_no_previous_versions(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}{RECIPE_PAGE}")
    wait_visible(driver, "h1")

    _open_timeline(driver)

    # No managed edit happened in this test, so no snapshots exist.
    wait_visible(driver, ".recipe-history__empty:not([hidden])")
    restore = driver.find_element(By.CSS_SELECTOR, ".recipe-history__restore")
    assert not restore.is_enabled()
