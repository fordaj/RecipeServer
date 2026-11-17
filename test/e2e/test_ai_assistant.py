"""End-to-end coverage for the floating AI assistant bubble.

The site is served from a throwaway recipe tree (see the shared fixtures).
A fake Ollama server stands in for the local model so the tests never touch
a real one; the browser is pointed at it by setting the configuration before
the page loads.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

import pytest
from selenium.webdriver.support.ui import WebDriverWait

from test.e2e.helpers import open_page, wait_text, wait_visible

import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By


class FakeOllamaHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send_json(200, {"models": [{"name": "test-model:latest"}]})
            return

        if self.path == "/api/ps":
            self._send_json(200, {"models": [{"name": "test-model:latest"}]})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._send_json(
            200,
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": "There are 16 tablespoons in a cup."},
                "done": True,
                "done_reason": "stop",
                "eval_count": 10,
                "eval_duration": 1_000_000_000,
            },
        )


@pytest.fixture()
def ollama_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture()
def ai_configured_server(recipe_server, ollama_server):
    recipe_server.cfg.model_endpoint = ollama_server
    recipe_server.cfg.all_purpose_model_name = "test-model"
    # handle_configuration() loads this at startup; the fixture builds the
    # Configuration directly, so set it here too.
    recipe_server.cfg.new_recipe_prompt = "Prompt"
    recipe_server.cfg.dictation_enabled = True
    return recipe_server


def assistant_class(driver) -> str:
    return driver.execute_script("return document.querySelector('.ai-assistant').className;")


def test_assistant_bubble_answers_questions(driver, ai_configured_server):
    open_page(driver, f"{ai_configured_server.url}/index.html")

    # The bubble appears once AI status reports the model is available.
    bubble = wait_visible(driver, ".ai-assistant__button")
    assert bubble.is_displayed()

    bubble.click()
    wait_visible(driver, ".ai-assistant__input")

    prompt = driver.find_element("css selector", ".ai-assistant__input")
    prompt.send_keys("How many tablespoons are in a cup?")
    driver.find_element("css selector", ".ai-assistant__send").click()

    wait_text(driver, ".ai-assistant__message--assistant", "16 tablespoons")


def test_assistant_bubble_hidden_when_ai_is_not_configured(driver, recipe_server):
    recipe_server.cfg.model_endpoint = ""
    open_page(driver, f"{recipe_server.url}/index.html")

    wait_visible(driver, 'li[data-testid="recipe-item"]')
    assert not driver.find_elements("css selector", ".ai-assistant__button")


def test_assistant_bubble_hides_on_scroll_down_and_returns_on_scroll_up(driver, ai_configured_server):
    driver.set_window_size(400, 800)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button")

    # Give the page something to scroll and jump to the bottom.
    driver.execute_script("document.body.style.minHeight = '2200px'; window.scrollTo(0, 1200);")

    WebDriverWait(driver, 5).until(lambda d: "ai-assistant--hidden" in assistant_class(d))

    # Scrolling back up brings the bubble back.
    driver.execute_script("window.scrollTo(0, 0);")
    WebDriverWait(driver, 5).until(lambda d: "ai-assistant--hidden" not in assistant_class(d))


def test_assistant_long_press_does_not_offer_dictation_without_https(driver, ai_configured_server):
    # The site under test is plain HTTP, so dictation must stay off: a long
    # press on the bubble behaves like a normal tap (the panel toggles) and
    # no microphone popup shows.
    open_page(driver, f"{ai_configured_server.url}/index.html")

    bubble = wait_visible(driver, ".ai-assistant__button")
    ActionChains(driver).click_and_hold(bubble).perform()
    time.sleep(0.7)
    ActionChains(driver).release(bubble).perform()

    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.CSS_SELECTOR, ".ai-assistant__button").get_attribute("aria-expanded") == "true")
    assert not driver.find_elements(By.CSS_SELECTOR, ".ai-assistant__mic--visible")


def test_assistant_long_press_does_not_offer_dictation_when_disabled(driver, ai_configured_server):
    ai_configured_server.cfg.dictation_enabled = False
    open_page(driver, f"{ai_configured_server.url}/index.html")

    bubble = wait_visible(driver, ".ai-assistant__button")
    ActionChains(driver).click_and_hold(bubble).perform()
    time.sleep(0.7)
    ActionChains(driver).release(bubble).perform()

    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.CSS_SELECTOR, ".ai-assistant__button").get_attribute("aria-expanded") == "true")
    assert not driver.find_elements(By.CSS_SELECTOR, ".ai-assistant__mic--visible")


def test_assistant_panel_closes_on_off_dialogue_click(driver, ai_configured_server):
    open_page(driver, f"{ai_configured_server.url}/index.html")

    bubble = wait_visible(driver, ".ai-assistant__button")
    bubble.click()
    wait_visible(driver, ".ai-assistant__panel")

    # A press that is both down and up off the dialogue closes it.
    heading = driver.find_element("css selector", ".recipes-header h1")
    heading.click()
    WebDriverWait(driver, 5).until(lambda d: d.find_element(By.CSS_SELECTOR, ".ai-assistant__button").get_attribute("aria-expanded") == "false")


def test_assistant_panel_survives_drag_out_of_dialogue(driver, ai_configured_server):
    open_page(driver, f"{ai_configured_server.url}/index.html")

    bubble = wait_visible(driver, ".ai-assistant__button")
    bubble.click()

    panel = wait_visible(driver, ".ai-assistant__panel")

    # Press inside the panel, release outside it: the dialogue must stay open.
    input_field = driver.find_element("css selector", ".ai-assistant__input")
    heading = driver.find_element("css selector", ".recipes-header h1")
    ActionChains(driver).click_and_hold(input_field).move_to_element(heading).release().perform()

    assert panel.get_attribute("aria-hidden") == "false"


def test_assistant_inline_mic_hidden_on_plain_http(driver, ai_configured_server):
    # The site under test is plain HTTP, so the inline dictation mic is not
    # offered (same gate as the long press).
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__input")
    assert not driver.find_elements("css selector", ".ai-assistant__mic-button")


def test_assistant_inline_mic_hidden_when_dictation_disabled(driver, ai_configured_server):
    ai_configured_server.cfg.dictation_enabled = False
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__input")
    assert not driver.find_elements("css selector", ".ai-assistant__mic-button")


def test_assistant_bubble_stays_visible_on_wide_screens(driver, ai_configured_server):
    driver.set_window_size(1280, 800)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button")
    driver.execute_script("document.body.style.minHeight = '2200px'; window.scrollTo(0, 1200);")
    WebDriverWait(driver, 5).until(lambda d: d.execute_script("return window.scrollY;") > 0)

    assert "ai-assistant--hidden" not in assistant_class(driver)
