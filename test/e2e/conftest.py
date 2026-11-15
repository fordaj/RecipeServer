"""Shared fixtures for the Selenium end-to-end tests in ``test/e2e``.

The fixtures here keep the browser tests isolated from real user data and from
any locally running RecipeServer instance:

- ``source_dir`` builds a throwaway recipe tree in a pytest-managed temporary
  directory (two recipes: a feature-rich sample with an image, and a minimal
  second recipe used for search/navigation tests).
- ``recipe_server`` points the ``Configuration`` at those temporary recipe and
  site directories, rebuilds the site, and starts a real ``Server`` on an
  ephemeral loopback port. The server and its builder callbacks are shut down
  when the test finishes, even if it fails.
- ``driver`` starts a WebDriver session. The browser, headless mode, and
  binary/driver overrides are configured through ``RECIPE_SERVER_TEST_*``
  environment variables.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from recipeserver.config import Configuration
from recipeserver.core import Core
from recipeserver.server import Server

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_RECIPE_DIR = REPO_ROOT / "test" / "recipes" / "sample"
ARTIFACTS_DIR = Path(os.environ.get("RECIPE_SERVER_TEST_ARTIFACTS", REPO_ROOT / ".e2e-artifacts"))

SECOND_RECIPE = """---
meals:
  - Dinner
categories:
  - Dessert
---

# Chocolate Cake

## Ingredients

- [ ] `2 cups` flour
- [ ] `1 cup` sugar

## Instructions

1. Mix the ingredients.
1. Bake at 350°F for 30 minutes.
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def source_dir(tmp_path: Path) -> Path:
    """A throwaway recipe tree with two recipes (one with an image)."""
    source = tmp_path / "source"

    waffles = source / "waffles"
    waffles.mkdir(parents=True)
    shutil.copy2(SAMPLE_RECIPE_DIR / "recipe.md", waffles / "recipe.md")
    shutil.copy2(SAMPLE_RECIPE_DIR / "image.png", waffles / "image.png")

    cake = source / "cake"
    cake.mkdir()
    (cake / "recipe.md").write_text(SECOND_RECIPE, encoding="utf-8")

    return source


@pytest.fixture()
def recipe_server(tmp_path: Path, source_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a site from the temporary recipe tree and serve it for one test.

    Yields a namespace with ``url``, ``cfg``, ``core``, ``site_dir``, and
    ``source_dir`` so tests can navigate with the browser and assert against
    the generated files.
    """
    site = tmp_path / "site"
    # The generated site normally lives in the platform user-data directory;
    # redirect it so the tests never touch real application data.
    monkeypatch.setattr(Configuration, "site_directory", property(lambda self: site))

    cfg = Configuration()
    cfg.source_directory = source_dir
    cfg.server_port = _free_port()

    core = Core(cfg)
    core.regen()

    server = Server(
        cfg,
        on_markdown_saved=core.on_markdown_save,
        on_config_saved=core.on_config_save,
        on_recipes_deleted=core.on_recipes_deleted,
    )
    server.start()
    try:
        yield SimpleNamespace(
            url=f"http://127.0.0.1:{cfg.server_port}",
            cfg=cfg,
            core=core,
            site_dir=site,
            source_dir=source_dir,
        )
    finally:
        server.stop()


def _headless() -> bool:
    return os.environ.get("RECIPE_SERVER_TEST_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}


def _chrome_options():
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if _headless():
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    binary = os.environ.get("RECIPE_SERVER_TEST_CHROME_BINARY")
    if binary:
        options.binary_location = binary
    # Keep browser console logs available for failure artifacts.
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    return options


def _firefox_options():
    from selenium.webdriver.firefox.options import Options

    options = Options()
    if _headless():
        options.add_argument("-headless")
    options.add_argument("--width=1280")
    options.add_argument("--height=900")
    binary = os.environ.get("RECIPE_SERVER_TEST_FIREFOX_BINARY")
    if binary:
        options.binary_location = binary
    return options


def _edge_options():
    from selenium.webdriver.edge.options import Options

    options = Options()
    if _headless():
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    binary = os.environ.get("RECIPE_SERVER_TEST_EDGE_BINARY")
    if binary:
        options.binary_location = binary
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    return options


def _chrome_service():
    from selenium.webdriver.chrome.service import Service

    path = os.environ.get("RECIPE_SERVER_TEST_CHROMEDRIVER")
    return Service(executable_path=path) if path else None


def _edge_service():
    from selenium.webdriver.edge.service import Service

    path = os.environ.get("RECIPE_SERVER_TEST_EDGEDRIVER")
    return Service(executable_path=path) if path else None


@pytest.fixture()
def driver():
    """A browser instance for one test.

    ``RECIPE_SERVER_TEST_BROWSER`` selects the browser (``chrome`` by
    default, also ``firefox`` and ``edge``). ``RECIPE_SERVER_TEST_HEADLESS``
    defaults to on. When the browser cannot be started, tests fail in CI and
    skip locally (set ``CI=true`` to force failure everywhere).
    """
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    browser = os.environ.get("RECIPE_SERVER_TEST_BROWSER", "chrome").strip().lower()
    try:
        if browser == "chrome":
            instance = webdriver.Chrome(options=_chrome_options(), service=_chrome_service())
        elif browser == "firefox":
            instance = webdriver.Firefox(options=_firefox_options())
        elif browser == "edge":
            instance = webdriver.Edge(options=_edge_options(), service=_edge_service())
        else:
            raise ValueError(f"Unsupported RECIPE_SERVER_TEST_BROWSER {browser!r}; expected 'chrome', 'firefox', or 'edge'.")
    except (WebDriverException, ValueError) as error:
        message = f"Could not start the {browser!r} WebDriver session: {error}. Install the browser or set RECIPE_SERVER_TEST_BROWSER."
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    instance.set_page_load_timeout(30)
    try:
        yield instance
    finally:
        instance.quit()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach a screenshot and browser console log to failed e2e tests."""
    report = yield
    if report.when != "call" or not report.failed:
        return report

    selenium_driver = item.funcargs.get("driver")
    if selenium_driver is None:
        return report

    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", item.name)

        screenshot_path = ARTIFACTS_DIR / f"{safe_name}.png"
        selenium_driver.save_screenshot(str(screenshot_path))
        report.sections.append(("e2e screenshot", f"failure screenshot saved to {screenshot_path}"))

        try:
            console_logs = selenium_driver.get_log("browser")
        except Exception:
            console_logs = []
        if console_logs:
            log_path = ARTIFACTS_DIR / f"{safe_name}-console.log"
            log_path.write_text(
                "\n".join(f"{entry.get('level')}: {entry.get('message')}" for entry in console_logs) + "\n",
                encoding="utf-8",
            )
            report.sections.append(("e2e browser console", f"console log saved to {log_path}"))
    except Exception as artifact_error:  # artifact capture must never mask the failure
        report.sections.append(("e2e artifact capture failed", repr(artifact_error)))

    return report
