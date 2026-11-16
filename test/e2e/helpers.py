"""Selenium helpers shared by the end-to-end tests.

All waits use ``WebDriverWait`` with explicit conditions; never sleep.
Selectors prefer the ``data-testid`` attributes emitted by the generator and
the existing stable element IDs over positional or class-based paths.
"""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_TIMEOUT = 10


def wait_visible(driver, css: str, timeout: int = DEFAULT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((By.CSS_SELECTOR, css)))


def wait_clickable(driver, css: str, timeout: int = DEFAULT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))


def wait_textarea_value(driver, css: str, timeout: int = DEFAULT_TIMEOUT):
    """Wait until a textarea has a non-empty value (the editor loads asynchronously)."""

    def _has_value(driver):
        element = driver.find_element(By.CSS_SELECTOR, css)
        return driver.execute_script("return arguments[0].value.length > 0;", element)

    return WebDriverWait(driver, timeout).until(_has_value)


def wait_hidden(driver, css: str, timeout: int = DEFAULT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, css)))


def wait_text(driver, css: str, text: str, timeout: int = DEFAULT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, css), text))


def click(driver, css: str, timeout: int = DEFAULT_TIMEOUT):
    wait_clickable(driver, css, timeout).click()


def open_page(driver, url: str):
    driver.get(url)


def visible_recipe_titles(driver) -> list[str]:
    """Titles of the recipe cards that are currently visible in the index."""
    elements = driver.find_elements(By.CSS_SELECTOR, 'li[data-testid="recipe-item"]:not([hidden])')
    return [element.get_attribute("data-title") for element in elements]


def severe_console_errors(driver) -> list[str]:
    """SEVERE-level browser console entries (Chrome/Edge only; [] elsewhere)."""
    try:
        entries = driver.get_log("browser")
    except Exception:
        return []
    return [entry.get("message", "") for entry in entries if entry.get("level") == "SEVERE"]
