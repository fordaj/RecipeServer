"""End-to-end coverage for dialogs and forms: menu, configuration, validation."""

from selenium.webdriver.common.by import By

from test.e2e.helpers import open_page, wait_clickable, wait_hidden, wait_visible


def _open_config_dialog(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")

    wait_clickable(driver, ".sandwich-menu__toggle").click()
    wait_visible(driver, ".sandwich-menu__panel:not([hidden])")

    wait_clickable(driver, '.sandwich-menu__item[data-config="open"]').click()
    wait_visible(driver, "#config-editor[open]")


def test_sandwich_menu_opens_and_closes(driver, recipe_server):
    open_page(driver, f"{recipe_server.url}/index.html")

    toggle = driver.find_element("css selector", ".sandwich-menu__toggle")
    assert toggle.get_attribute("aria-expanded") == "false"

    wait_clickable(driver, ".sandwich-menu__toggle").click()
    wait_visible(driver, ".sandwich-menu__panel:not([hidden])")
    assert toggle.get_attribute("aria-expanded") == "true"

    wait_clickable(driver, ".sandwich-menu__toggle").click()
    wait_hidden(driver, ".sandwich-menu__panel")
    assert toggle.get_attribute("aria-expanded") == "false"


def test_configuration_dialog_opens_and_closes(driver, recipe_server):
    _open_config_dialog(driver, recipe_server)

    # The dialog renders one input per server-supplied field spec.
    wait_visible(driver, "#config-editor-server_port")
    wait_visible(driver, "#config-editor-source_directory")

    wait_clickable(driver, ".config-editor__cancel").click()
    wait_hidden(driver, "#config-editor")


def test_configuration_form_surfaces_server_validation_errors(driver, recipe_server):
    _open_config_dialog(driver, recipe_server)

    food_color = wait_visible(driver, "#config-editor-food_color")
    food_color.clear()
    food_color.send_keys("not-a-color")

    wait_clickable(driver, ".config-editor__save").click()

    status = wait_visible(driver, ".config-editor__status")
    assert "Food color" in status.text

    # The dialog stays open so the user can fix the value.
    assert driver.find_element("css selector", "#config-editor").get_attribute("open") is not None


def test_dictation_can_be_disabled_from_the_configuration_dialog(driver, recipe_server):
    # Keep the save from writing to the real user-data configuration file.
    recipe_server.cfg._config_file = recipe_server.site_dir / "test-cfg.toml"

    _open_config_dialog(driver, recipe_server)

    checkbox = wait_visible(driver, "#config-editor-dictation_enabled")
    assert checkbox.get_attribute("type") == "checkbox"
    assert checkbox.is_selected()

    checkbox.click()

    wait_clickable(driver, ".config-editor__save").click()

    # Saving reloads the page; the dictation button is no longer rendered.
    wait_visible(driver, 'li[data-testid="recipe-item"]')
    buttons = driver.find_elements(By.CSS_SELECTOR, '[data-testid="speech-button"]')
    assert buttons == []
    assert recipe_server.cfg.dictation_enabled is False
    assert driver.find_element(By.CSS_SELECTOR, '[data-testid="recipe-search"]').is_displayed()
