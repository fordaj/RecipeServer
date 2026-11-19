"""Tests for the chat Markdown renderer and the /api/assistant-markdown endpoint.

The assistant's and the user's messages both render through this path, with
the same strategy the recipe pages use (Python-Markdown + quantity spans),
plus sanitization because chat messages (especially model replies) are not
trusted input.
"""

import json

import frontmatter

from recipeserver.assistant_render import MAX_RENDER_CHARS, render_chat_markdown

from .helpers import request_json, running_recipe_server, write_recipe


def test_render_chat_markdown_rewrites_quantity_code():
    html = render_chat_markdown("Use `1 1/2 cups` flour and `1-2 tbsp` oil.")

    assert '<span class="quantity" data-quantity="1.5" data-unit="cup"></span>' in html
    assert '<span class="quantity" data-quantity="1.0" data-quantity-end="2.0" data-unit="tbsp"></span>' in html


def test_render_chat_markdown_leaves_plain_code_alone():
    html = render_chat_markdown("Run `npm test` to check.")

    assert "<code>npm test</code>" in html
    assert "quantity" not in html


def test_render_chat_markdown_wraps_math_in_arithmatex_spans():
    html = render_chat_markdown("The answer is $x^2$.")

    assert '<span class="arithmatex">\\(x^2\\)</span>' in html


def test_render_chat_markdown_renders_display_math():
    html = render_chat_markdown("$$e^{i\\pi} = -1$$")

    assert '<div class="arithmatex">\\[e^{i\\pi} = -1\\]</div>' in html


def test_render_chat_markdown_renders_task_lists():
    html = render_chat_markdown("- [ ] buy milk\n- [x] eggs")

    assert html.count("<li") == 2
    assert 'type="checkbox"' in html
    assert "checked" in html


def test_render_chat_markdown_strips_script_tags():
    html = render_chat_markdown("Hello <script>alert('xss')</script> world")

    assert "<script" not in html
    assert "alert" not in html


def test_render_chat_markdown_strips_event_handlers_and_styles():
    html = render_chat_markdown('<img src="https://example.com/x.png" onerror="alert(1)" style="width:100%">')

    assert "onerror" not in html
    assert "style=" not in html
    assert 'src="https://example.com/x.png"' in html


def test_render_chat_markdown_drops_javascript_urls():
    html = render_chat_markdown('<a href="javascript:alert(1)">click</a>')

    assert 'href="javascript' not in html
    assert ">click</a>" in html


def test_render_chat_markdown_allows_https_links_and_marks_them_external():
    html = render_chat_markdown("[Example](https://example.com/recipe)")

    assert 'href="https://example.com/recipe"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_render_chat_markdown_allows_root_absolute_links():
    html = render_chat_markdown("[Local](/dinners/pasta/recipe.html)")

    assert 'href="/dinners/pasta/recipe.html"' in html
    # Local links are not opened in a new tab.
    assert "target=" not in html


def test_render_chat_markdown_drops_data_urls():
    html = render_chat_markdown('<img src="data:text/html;base64,PHI+PHNjcmlwdD4=">')

    assert "data:text/html" not in html


def test_render_chat_markdown_strips_forms_and_embeds():
    html = render_chat_markdown('<form action="https://evil.example"><input name="q"></form><iframe src="https://evil.example"></iframe>')

    assert "<form" not in html
    assert "<iframe" not in html
    assert "<input name" not in html


def test_render_chat_markdown_keeps_math_free_text_untouched():
    html = render_chat_markdown("Just text, no markup.")

    assert "Just text, no markup." in html


def test_render_chat_markdown_rejects_non_strings():
    try:
        render_chat_markdown(None)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected a ValueError for non-string input")


def test_render_chat_markdown_rejects_oversized_input():
    try:
        render_chat_markdown("x" * (MAX_RENDER_CHARS + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected a ValueError for oversized input")


def test_assistant_markdown_endpoint(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()
    write_recipe(source / "dinners" / "pasta" / "recipe.md", "meals:\n  - Dinner\n", "# Pasta\n\nBody.\n")

    with running_recipe_server(source) as (base_url, _saved, _deleted):
        status, body = request_json(
            f"{base_url}/api/assistant-markdown",
            {"markdown": "Add `2 cloves` garlic <script>alert(1)</script>"},
        )

    assert status == 200
    assert '<span class="quantity" data-quantity="2.0" data-unit="cloves"></span>' in body["html"]
    assert "<script" not in body["html"]


def test_assistant_markdown_endpoint_rejects_empty_markdown(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_recipe_server(source) as (base_url, _saved, _deleted):
        status, body = request_json(f"{base_url}/api/assistant-markdown", {"markdown": "   "})
        assert status == 400

        status, body = request_json(f"{base_url}/api/assistant-markdown", {"wrong": "key"})
        assert status == 400


def test_assistant_markdown_endpoint_rejects_non_object_payload(tmp_path):
    source = tmp_path / "recipes"
    source.mkdir()

    with running_recipe_server(source) as (base_url, _saved, _deleted):
        status, _body = request_json(f"{base_url}/api/assistant-markdown", ["not", "an", "object"])

    assert status == 400
