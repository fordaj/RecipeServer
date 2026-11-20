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
    # Subclasses may carry a scripted queue of /api/chat responses; when the
    # queue is empty (or absent) the fixed default reply is sent.
    state: dict = {}

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

        responses = type(self).state.get("responses")
        if responses:
            self._send_json(200, responses.pop(0))
            return

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


def scripted_ollama_server(responses):
    """Start a fake Ollama server that plays back a scripted queue of replies."""
    handler = type("ScriptedOllamaHandler", (FakeOllamaHandler,), {"state": {"responses": list(responses)}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def tool_call_response(name, arguments, content: str = ""):
    return {
        "model": "test-model",
        "message": {
            "role": "assistant",
            "content": content,
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        },
        "done": True,
        "done_reason": "stop",
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
    }


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


def wait_panel_settled(driver) -> None:
    """Wait out the panel's open transition before measuring geometry.

    The panel animates from ``scale(0.96)``/translated to its resting state
    over 200ms; ``getBoundingClientRect`` reports interpolated values until
    then, which would measure a shrunken card and a displaced sheet.
    """

    WebDriverWait(driver, 5).until(
        lambda d: d.execute_script(
            "const panel = document.querySelector('.ai-assistant__panel');" "return panel && getComputedStyle(panel).transform === 'none';"
        )
    )


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


def test_assistant_mobile_sheet_fills_the_screen_above_the_orb(driver, ai_configured_server):
    driver.set_window_size(390, 844)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__panel")
    wait_panel_settled(driver)

    rect = driver.execute_script("""
        const panel = document.querySelector('.ai-assistant__panel').getBoundingClientRect();
        const orb = document.querySelector('.ai-assistant__button').getBoundingClientRect();
        return {
          panel: { top: panel.top, bottom: panel.bottom, left: panel.left, right: panel.right, height: panel.height },
          orb: { top: orb.top, bottom: orb.bottom },
          viewport: { width: document.documentElement.clientWidth, height: window.innerHeight },
        };
        """)

    panel, orb, viewport = rect["panel"], rect["orb"], rect["viewport"]

    # A full-width sheet: no horizontal margins.
    assert panel["left"] <= 1
    assert panel["right"] >= viewport["width"] - 1

    # It fills 75-95% of the dynamic viewport and starts near the top.
    # Measured against innerHeight, with a few pixels of tolerance for the
    # dvh/innerHeight rounding differences across platforms.
    share = panel["height"] / viewport["height"]
    assert 0.75 <= share <= 0.95
    assert -1 <= panel["top"] <= viewport["height"] * 0.05

    # The orb stays visible and tappable below the sheet.
    assert orb["top"] >= panel["bottom"] - 1
    assert orb["bottom"] <= viewport["height"] + 1


@pytest.mark.parametrize("width", [1440, 1024, 768])
def test_assistant_panel_is_a_floating_card_anchored_to_the_orb(driver, ai_configured_server, width):
    driver.set_window_size(width, 900)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__panel")
    wait_panel_settled(driver)

    rect = driver.execute_script("""
        const panel = document.querySelector('.ai-assistant__panel').getBoundingClientRect();
        const orb = document.querySelector('.ai-assistant__button').getBoundingClientRect();
        return {
          panel: { top: panel.top, bottom: panel.bottom, left: panel.left, right: panel.right, width: panel.width },
          orb: { top: orb.top, right: orb.right },
        };
        """)

    panel, orb = rect["panel"], rect["orb"]

    # The floating card is 360-420px wide and is not full-bleed.
    assert 360 <= panel["width"] <= 420
    assert panel["left"] >= 1

    # It is right-aligned with the orb and rests just above it, so the
    # launcher is never covered.
    assert abs(panel["right"] - orb["right"]) <= 2
    assert orb["top"] >= panel["bottom"] - 1


def test_assistant_sheet_does_not_overflow_a_narrow_screen(driver, ai_configured_server):
    driver.set_window_size(320, 568)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__panel")
    wait_panel_settled(driver)

    metrics = driver.execute_script("""
        const panel = document.querySelector('.ai-assistant__panel').getBoundingClientRect();
        const doc = document.documentElement;
        return {
          left: panel.left,
          right: panel.right,
          clientWidth: doc.clientWidth,
          scrollWidth: doc.scrollWidth,
        };
        """)

    # Neither the sheet nor the page overflows horizontally at 320px.
    assert metrics["left"] >= -1
    assert metrics["right"] <= metrics["clientWidth"] + 1
    assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1


def test_assistant_send_waits_for_something_to_send(driver, ai_configured_server):
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__input")

    send = wait_visible(driver, ".ai-assistant__send")
    prompt = driver.find_element("css selector", ".ai-assistant__input")

    # Nothing to send yet: the button waits.
    assert send.get_attribute("disabled") is not None

    prompt.send_keys("Hello")
    assert send.get_attribute("disabled") is None

    # Emptying the composer (through the input event the browser fires)
    # disables it again.
    driver.execute_script("""
        const input = document.querySelector('.ai-assistant__input');
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        """)
    assert send.get_attribute("disabled") is not None


def test_assistant_controls_meet_touch_and_type_minimums(driver, ai_configured_server):
    driver.set_window_size(390, 844)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__input")
    wait_panel_settled(driver)

    metrics = driver.execute_script("""
        const close = document.querySelector('.ai-assistant__close').getBoundingClientRect();
        const send = document.querySelector('.ai-assistant__send').getBoundingClientRect();
        const input = document.querySelector('.ai-assistant__input');
        return {
          close: { width: close.width, height: close.height },
          send: { width: send.width, height: send.height },
          inputFontSize: parseFloat(getComputedStyle(input).fontSize),
        };
        """)

    # 44px touch targets and 16px text (iOS Safari zooms smaller text).
    assert metrics["close"]["width"] >= 44
    assert metrics["close"]["height"] >= 44
    assert metrics["send"]["width"] >= 44
    assert metrics["send"]["height"] >= 44
    assert metrics["inputFontSize"] >= 16


def test_assistant_placeholder_is_not_clipped_by_the_dictation_layout(driver, ai_configured_server):
    driver.set_window_size(1280, 800)
    open_page(driver, f"{ai_configured_server.url}/index.html")

    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__input")

    wraps = driver.execute_script("""
        const input = document.querySelector('.ai-assistant__input');
        // Reproduce the dictation layout (it reserves room for the inline
        // mic), which is otherwise only used over HTTPS in this HTTP test.
        input.parentElement.classList.add('ai-assistant__field--dictation');
        const original = input.value;
        input.value = input.placeholder;
        const wraps = input.scrollHeight > input.clientHeight + 1;
        input.value = original;
        return wraps;
        """)
    assert wraps is False


def test_pull_to_refresh_disabled_while_assistant_is_open(driver, ai_configured_server):
    if not driver.execute_script("return typeof Touch !== 'undefined' && typeof TouchEvent !== 'undefined';"):
        pytest.skip("Touch events are not available in this browser")

    open_page(driver, f"{ai_configured_server.url}/index.html")
    WebDriverWait(driver, 5).until(lambda d: d.find_elements(By.CSS_SELECTOR, "#pull-to-refresh"))

    # A short pull (below the refresh threshold) activates the indicator but
    # does not reload the page, so the same gesture can be repeated.
    pull = """
      const fire = (type, y) => {
        const touch = new Touch({ identifier: 1, target: document.body, clientX: 10, clientY: y });
        return new TouchEvent(type, {
          bubbles: true,
          cancelable: true,
          touches: type === 'touchend' ? [] : [touch],
          targetTouches: type === 'touchend' ? [] : [touch],
          changedTouches: [touch],
        });
      };
      window.scrollTo(0, 0);
      document.dispatchEvent(fire('touchstart', 100));
      const move = fire('touchmove', 150);
      document.dispatchEvent(move);
      const active = document.getElementById('pull-to-refresh').classList.contains('ptr-active');
      document.dispatchEvent(fire('touchend', 150));
      return { active, prevented: move.defaultPrevented };
    """

    # With the dialogue closed, pull-to-refresh responds as usual.
    closed = driver.execute_script(pull)
    assert closed["active"] is True
    assert closed["prevented"] is True

    # With the dialogue open, the same gesture is ignored entirely.
    wait_visible(driver, ".ai-assistant__button").click()
    wait_visible(driver, ".ai-assistant__panel")
    opened = driver.execute_script(pull)
    assert opened["active"] is False
    assert opened["prevented"] is False


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


def test_assistant_messages_render_markdown(driver, ai_configured_server):
    markdown_reply = (
        "Here is the list:\n\n" "- **1 cup** flour\n" "- `2 tbsp` sugar\n\n" "Plain `npm test` stays a code chip; `1 1/2 cups` gets KaTeX."
    )
    server = scripted_ollama_server(
        [
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": markdown_reply},
                "done": True,
                "done_reason": "stop",
                "eval_count": 10,
                "eval_duration": 1_000_000_000,
            }
        ]
    )
    ai_configured_server.cfg.model_endpoint = f"http://127.0.0.1:{server.server_port}"

    try:
        open_page(driver, f"{ai_configured_server.url}/index.html")

        bubble = wait_visible(driver, ".ai-assistant__button")
        bubble.click()
        wait_visible(driver, ".ai-assistant__input")

        driver.find_element("css selector", ".ai-assistant__input").send_keys("What do I need?")
        driver.find_element("css selector", ".ai-assistant__send").click()

        # The reply arrives as Markdown and is rendered as HTML in place.
        wait_visible(driver, ".ai-assistant__message--assistant li strong")
        strong = driver.find_element("css selector", ".ai-assistant__message--assistant li strong")
        assert strong.text == "1 cup"

        # Inline-code quantities are rewritten to .quantity spans and typeset by KaTeX.
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script(
                "const el = document.querySelector('.ai-assistant__message--assistant .quantity');"
                "return el && el.querySelector('.katex') !== null;"
            )
        )

        # The user's own message renders as Markdown too (a bold word renders as <strong>).
        wait_visible(driver, ".ai-assistant__message--user")
        assert driver.find_element("css selector", ".ai-assistant__message--user").text.strip() != ""
    finally:
        server.shutdown()
        server.server_close()


def test_assistant_open_recipe_redirects_to_the_match(driver, ai_configured_server):
    server = scripted_ollama_server(
        [
            tool_call_response("open_recipe", {"query": "chocolate cake"}),
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": "Opening Chocolate Cake…"},
                "done": True,
                "done_reason": "stop",
                "eval_count": 10,
                "eval_duration": 1_000_000_000,
            },
        ]
    )
    ai_configured_server.cfg.model_endpoint = f"http://127.0.0.1:{server.server_port}"

    try:
        open_page(driver, f"{ai_configured_server.url}/index.html")

        bubble = wait_visible(driver, ".ai-assistant__button")
        bubble.click()
        wait_visible(driver, ".ai-assistant__input")

        driver.find_element("css selector", ".ai-assistant__input").send_keys("Open chocolate cake")
        driver.find_element("css selector", ".ai-assistant__send").click()

        WebDriverWait(driver, 10).until(lambda d: d.current_url.endswith("/cake/recipe.html"))
        assert driver.find_element("css selector", "h1").text.strip() == "Chocolate Cake"
    finally:
        server.shutdown()
        server.server_close()
