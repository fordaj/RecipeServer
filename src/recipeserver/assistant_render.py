"""Render chat Markdown (user and assistant messages) to a safe HTML fragment.

The assistant and the user both write Markdown in the chat panel, so the
messages are rendered with the same strategy the recipe pages use:

- Python-Markdown with the same extension set (``pymdownx.extra``,
  ``pymdownx.blocks.html``, ``pymdownx.tasklist`` and ``pymdownx.arithmatex``),
  the latter in ``generic`` mode so LaTeX math lands in ``\\(...\\)`` /
  ``\\[...\\]`` spans that the vendored KaTeX auto-render can typeset in the
  browser.
- Inline-code quantities (``1 1/2 cups``) are rewritten to ``.quantity``
  spans with ``data-quantity``/``data-unit``/``data-quantity-end`` attributes
  by the same ``quantities`` module the recipe pipeline uses; the browser
  renders them with KaTeX at 1x scale (the chat has no scaler controls).

Unlike recipe bodies, chat messages are not trusted input, so the rendered
fragment is sanitized afterwards: raw HTML from the source is removed or
neutralized (no scripts, no event handlers, no ``javascript:`` URLs, no
forms, only disabled checkboxes), so a hostile or broken model reply cannot
run code in the page.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import markdown
from bs4 import BeautifulSoup

from .markdown_to_html import quantities

# Upper cap on a single render call. Assistant replies are bounded by the
# model token limit; this also bounds user-typed messages and keeps the
# endpoint from becoming an unbounded HTML factory.
MAX_RENDER_CHARS = 100_000

# Tags that never survive sanitization; the KaTeX math the browser renders
# itself is built from ``<span>``/``<div>``/``<math>`` elements, none of which
# the model is allowed to emit here (KaTeX never consumes them).
_BLOCKED_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "base",
    "link",
    "meta",
    "svg",
    "math",
    "audio",
    "video",
    "button",
    "select",
    "textarea",
    "noscript",
    "template",
}

_URL_ATTRIBUTES = ("href", "src")
_ALLOWED_URL_SCHEMES = ("http", "https", "mailto")
_EXTERNAL_SCHEMES = ("http", "https")


def _is_allowed_url(value: str) -> bool:
    text = value.strip()
    # Fragments and schemeless relative URLs are always fine.
    if text.startswith("#"):
        return True
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if not parts.scheme:
        return True
    return parts.scheme.lower() in _ALLOWED_URL_SCHEMES


def _sanitize(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()

        if not isinstance(tag.attrs, dict):
            # A parent was decomposed earlier in this loop; the orphaned
            # child's attributes are gone too.
            continue

        if name in _BLOCKED_TAGS:
            tag.decompose()
            continue

        if name == "input":
            # Only task-list checkboxes survive, and only disabled.
            input_type = (tag.get("type") or "").lower()
            if input_type != "checkbox":
                tag.decompose()
                continue
            checked = tag.has_attr("checked")
            tag.attrs = {"type": "checkbox", "disabled": ""}
            if checked:
                tag.attrs["checked"] = ""
            continue

        for attribute in list(tag.attrs):
            lowered = attribute.lower()
            if lowered.startswith("on") or lowered in ("style", "id", "srcdoc", "formaction", "xlink:href"):
                del tag.attrs[attribute]
                continue
            if lowered in _URL_ATTRIBUTES and not _is_allowed_url(str(tag.get(attribute) or "")):
                del tag.attrs[attribute]

    # External links open in a new tab so the (ephemeral) conversation
    # survives the click.
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().lower()
        if href.startswith(_EXTERNAL_SCHEMES):
            anchor["target"] = "_blank"
            anchor["rel"] = "noopener noreferrer"


def render_chat_markdown(text: str) -> str:
    """Render a Markdown string to a sanitized HTML fragment for the chat."""
    if not isinstance(text, str):
        raise ValueError("Expected a Markdown string")
    if len(text) > MAX_RENDER_CHARS:
        raise ValueError(f"The Markdown is too long (at most {MAX_RENDER_CHARS} characters)")

    renderer = markdown.Markdown(
        extensions=[
            "pymdownx.extra",
            "pymdownx.blocks.html",
            "pymdownx.tasklist",
            "pymdownx.arithmatex",
        ],
        extension_configs={"pymdownx.arithmatex": {"generic": True}},
    )
    body = renderer.convert(text)

    soup = BeautifulSoup(body, "html.parser")
    quantities.convert_quantity_code_spans(soup)
    _sanitize(soup)
    return str(soup)
