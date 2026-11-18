"""End-to-end coverage for the bulk editor's Apply/Discard Edits flow."""

from __future__ import annotations

import frontmatter
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from test.e2e.helpers import DEFAULT_TIMEOUT, open_page, wait_clickable, wait_hidden, wait_visible


def _open_bulk_editor(driver, recipe_server, count=2):
    open_page(driver, f"{recipe_server.url}/index.html")
    wait_clickable(driver, "#bulk-selection-toggle").click()
    wait_clickable(driver, "#select-all").click()
    wait_clickable(driver, "#bulk-edit").click()
    wait_visible(driver, "#recipe-markdown-editor[open]")
    # The dialog opens before the recipes arrive from the server; wait for the
    # loading status to clear and the selection panel to fill in.
    WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.text_to_be_present_in_element((By.CSS_SELECTOR, ".recipe-editor__bulk-list-title"), f"Editing {count} recipes")
    )


def _makes_field(driver):
    # The Details section starts collapsed; expand it to reach the fields.
    xpath = "//details[./summary[normalize-space(.)='Details']]"
    details = driver.find_element(By.XPATH, xpath)
    if details.get_attribute("open") is None:
        WebDriverWait(driver, DEFAULT_TIMEOUT).until(EC.element_to_be_clickable((By.XPATH, f"{xpath}/summary"))).click()
    return wait_visible(driver, ".recipe-editor__metadata input[name='makes']")


def test_bulk_edit_applies_only_modified_attributes(driver, recipe_server):
    waffles = recipe_server.source_dir / "waffles" / "recipe.md"
    cake = recipe_server.source_dir / "cake" / "recipe.md"

    _open_bulk_editor(driver, recipe_server)

    heading = driver.find_element(By.CSS_SELECTOR, ".recipe-editor__header h2").text
    assert heading == "Bulk Edit Recipes (2 selected)"
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-editor__save").text == "Apply Edits"
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-editor__cancel").text == "Discard Edits"
    # The list of target recipes is shown, and nothing is modified yet.
    assert "waffles/recipe.md" in driver.find_element(By.CSS_SELECTOR, ".recipe-editor__bulk-list").text
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-editor__modified-summary").get_attribute("hidden") is not None
    # Loaded values that differ across the selection are flagged MIXED.
    for label_text in ("Meals", "Categories"):
        mixed = driver.find_element(
            By.XPATH,
            f"//label[contains(., '{label_text}')]//span[contains(@class, 'recipe-editor__mixed')]",
        )
        assert mixed.is_displayed(), label_text
    # Identical values carry no MIXED chip.
    contributor_mixed = driver.find_element(
        By.XPATH,
        "//label[contains(., 'Contributor')]//span[contains(@class, 'recipe-editor__mixed')]",
    )
    assert not contributor_mixed.is_displayed()

    makes = _makes_field(driver)
    makes.clear()
    makes.send_keys("12")

    summary = driver.find_element(By.CSS_SELECTOR, ".recipe-editor__modified-summary")
    WebDriverWait(driver, DEFAULT_TIMEOUT).until(lambda _: "Modified: Makes" in summary.text)

    wait_clickable(driver, ".recipe-editor__save").click()

    # The Apply confirmation restates the changes before anything is written.
    alert = WebDriverWait(driver, DEFAULT_TIMEOUT).until(EC.alert_is_present())
    assert "Update the following for 2 recipes?" in alert.text
    assert "Makes" in alert.text
    alert.accept()

    # The editor reloads the page after a successful apply.
    wait_visible(driver, "#recipe-list")

    waffles_md = frontmatter.loads(waffles.read_text(encoding="utf-8")).metadata
    cake_md = frontmatter.loads(cake.read_text(encoding="utf-8")).metadata
    assert waffles_md["makes"] == 12
    assert cake_md["makes"] == 12
    # Untouched attributes are not overwritten.
    assert cake_md["categories"] == ["Dessert"]
    assert cake_md["meals"] == ["Dinner"]


def test_bulk_edit_mixed_chip_flips_to_modified(driver, recipe_server):
    _open_bulk_editor(driver, recipe_server)

    # Meals differ across the two recipes, so it opens flagged MIXED…
    mixed = driver.find_element(
        By.XPATH,
        "//label[contains(., 'Meals')]//span[contains(@class, 'recipe-editor__mixed')]",
    )
    assert mixed.is_displayed()

    # …and once the field is edited, the chip flips to Modified.
    remove = driver.find_element(
        By.XPATH,
        "//label[contains(., 'Meals')]//button[contains(@class, 'recipe-editor__picker-chip-remove')]",
    )
    remove.click()

    summary = driver.find_element(By.CSS_SELECTOR, ".recipe-editor__modified-summary")
    WebDriverWait(driver, DEFAULT_TIMEOUT).until(lambda _: "Modified: Meals" in summary.text)
    assert not mixed.is_displayed()


def test_bulk_edit_apply_confirmation_can_be_cancelled(driver, recipe_server):
    cake = recipe_server.source_dir / "cake" / "recipe.md"

    _open_bulk_editor(driver, recipe_server)

    makes = _makes_field(driver)
    makes.clear()
    makes.send_keys("12")

    wait_clickable(driver, ".recipe-editor__save").click()
    alert = WebDriverWait(driver, DEFAULT_TIMEOUT).until(EC.alert_is_present())
    alert.dismiss()

    # Dismissing the confirmation keeps the dialog open and writes nothing.
    assert driver.find_element(By.CSS_SELECTOR, ".recipe-editor__modified-summary").text == "Modified: Makes"
    assert frontmatter.loads(cake.read_text(encoding="utf-8")).metadata.get("makes") is None


def test_bulk_edit_discard_edits_closes_without_saving(driver, recipe_server):
    cake = recipe_server.source_dir / "cake" / "recipe.md"
    original = cake.read_text(encoding="utf-8")

    _open_bulk_editor(driver, recipe_server)

    makes = _makes_field(driver)
    makes.clear()
    makes.send_keys("12")

    wait_clickable(driver, ".recipe-editor__cancel").click()
    wait_hidden(driver, "#recipe-markdown-editor")

    assert cake.read_text(encoding="utf-8") == original
