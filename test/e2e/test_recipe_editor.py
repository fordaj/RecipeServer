"""End-to-end coverage for the in-browser recipe editor."""

from test.e2e.helpers import open_page, wait_clickable, wait_hidden, wait_textarea_value, wait_text, wait_visible


def _open_editor(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/waffles/recipe.html")
    wait_clickable(driver, "#edit-recipe").click()
    wait_visible(driver, "#recipe-markdown-editor[open]")
    # The dialog opens before the Markdown arrives from the server; wait for
    # the load to finish so the textarea is not overwritten after the test
    # edits it.
    wait_textarea_value(driver, ".recipe-editor__source")


def test_editor_opens_and_shows_existing_content(driver, recipe_server):
    _open_editor(driver, recipe_server)

    textarea = driver.find_element("css selector", ".recipe-editor__source")
    assert "# Sample" in textarea.get_attribute("value")


def test_editor_cancel_closes_without_saving(driver, recipe_server):
    original = (recipe_server.source_dir / "waffles" / "recipe.md").read_text(encoding="utf-8")

    _open_editor(driver, recipe_server)
    textarea = driver.find_element("css selector", ".recipe-editor__source")
    driver.execute_script(
        "arguments[0].value = arguments[0].value + '\\nCHANGED-MARKER\\n';" "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
        textarea,
    )

    wait_clickable(driver, ".recipe-editor__cancel").click()
    wait_hidden(driver, "#recipe-markdown-editor")

    assert (recipe_server.source_dir / "waffles" / "recipe.md").read_text(encoding="utf-8") == original
    assert "CHANGED-MARKER" not in driver.find_element("css selector", "h1").text


def test_editor_save_updates_page_and_markdown_file(driver, recipe_server):
    recipe_file = recipe_server.source_dir / "waffles" / "recipe.md"
    original = recipe_file.read_text(encoding="utf-8")

    _open_editor(driver, recipe_server)
    textarea = driver.find_element("css selector", ".recipe-editor__source")
    driver.execute_script(
        "arguments[0].value = arguments[0].value.replace('# Sample', '# Sample Deluxe');"
        "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));",
        textarea,
    )

    wait_clickable(driver, ".recipe-editor__save").click()

    # The editor reloads the page after a successful save.
    wait_text(driver, "h1", "Sample Deluxe")

    updated = recipe_file.read_text(encoding="utf-8")
    assert "# Sample Deluxe" in updated
    assert updated != original


def test_editor_details_sections_expand_and_collapse(driver, recipe_server):
    _open_editor(driver, recipe_server)

    details_selector = ".recipe-editor__markdown-details"
    summary_selector = f"{details_selector} > summary"
    assert driver.find_element("css selector", details_selector).get_attribute("open") is None

    wait_clickable(driver, summary_selector).click()
    assert driver.find_element("css selector", details_selector).get_attribute("open") is not None

    wait_clickable(driver, summary_selector).click()
    assert driver.find_element("css selector", details_selector).get_attribute("open") is None
