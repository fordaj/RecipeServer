"""Edit image references inside recipe Markdown.

The image APIs rename, delete, and choose the hero image by rewriting the
Markdown source. Those are text rules, not HTTP rules, so they live here
independently of the request handler that calls them.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

# Match a Markdown image reference: the src token (optionally in angle brackets)
# followed by an optional title and the closing paren. Only the src is captured.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*(?P<image_src><[^>\n]*>|[^)\s>]+)(?:(?:\s+\"[^\"]*\")?\s*\))")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"'](?P<image_src>[^\"']+)[\"']", re.IGNORECASE)
_EXTERNAL_SRC_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def image_name_pattern(name: str) -> re.Pattern:
    """Match ``name`` only when it is not glued to more filename characters.

    A plain substring replace would corrupt references such as
    ``chocolate-cake.png`` when renaming ``cake.png``.
    """
    return re.compile(r"(?P<prefix>^|[^A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])")


def replace_image_reference(content: str, source: str, target: str) -> str:
    """Replace every reference to *source* with *target*, including URL escapes."""
    updated = image_name_pattern(source).sub(lambda match: match.group("prefix") + target, content)
    quoted_source = quote(source)
    if quoted_source != source:
        updated = image_name_pattern(quoted_source).sub(lambda match: match.group("prefix") + quote(target), updated)
    return updated


def is_external_src(src: str) -> bool:
    return _EXTERNAL_SRC_RE.match(src) is not None


def basename_of_src(src: str) -> str:
    clean = src.split("?", 1)[0].split("#", 1)[0]
    clean = clean.replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    segments = [segment for segment in clean.split("/") if segment]
    return unquote(segments[-1]) if segments else ""


def first_image_reference(content: str) -> dict | None:
    """Locate the first image in the Markdown, Markdown or HTML syntax."""
    candidates: list[dict] = []
    for match in _MARKDOWN_IMAGE_RE.finditer(content):
        src_raw = match.group("image_src")
        src = src_raw[1:-1] if src_raw.startswith("<") and src_raw.endswith(">") else src_raw
        candidates.append(
            {
                "span_start": match.start(),
                "span_end": match.end(),
                "src_start": match.start("image_src"),
                "src_end": match.end("image_src"),
                "src": src,
                "kind": "markdown",
            }
        )
    for match in _HTML_IMG_RE.finditer(content):
        span_end = match.end()
        closing = content.find(">", match.end())
        if closing != -1:
            span_end = closing + 1
        candidates.append(
            {
                "span_start": match.start(),
                "span_end": span_end,
                "src_start": match.start("image_src"),
                "src_end": match.end("image_src"),
                "src": match.group("image_src"),
                "kind": "html",
            }
        )
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate["span_start"])


def remove_image_span(content: str, span_start: int, span_end: int) -> str:
    """Remove the image; when it sits alone on its line, drop the line too."""
    line_start = content.rfind("\n", 0, span_start) + 1
    line_end_index = content.find("\n", span_end)
    line_end = line_end_index if line_end_index != -1 else len(content)
    before = content[line_start:span_start]
    after = content[span_end:line_end]
    if before.strip() == "" and after.strip() == "":
        remove_end = line_end + 1 if line_end < len(content) and content[line_end] == "\n" else line_end
        return content[:line_start] + content[remove_end:]
    return content[:span_start] + content[span_end:]


def fallback_main_image(content: str, deleted_name: str, remaining_names: list[str]) -> tuple[str | None, str | None]:
    """Point the main image at a still-existing file after a delete.

    The main image is the first image link in the Markdown. If it pointed at
    the deleted file, rewrite it to the first remaining image alphabetically;
    with none remaining, remove the dangling link. Returns
    (updated_content, fallback_name) or (None, None) when nothing changed.
    """
    first = first_image_reference(content)
    if first is None or is_external_src(first["src"]):
        return None, None
    if basename_of_src(first["src"]) != deleted_name:
        return None, None

    if remaining_names:
        target = remaining_names[0]
        if first["kind"] == "html":
            replacement = target.replace("&", "&amp;").replace('"', "&quot;")
        elif re.search(r"[\s<>()]", target):
            replacement = f"<{target}>"
        else:
            replacement = target
        return content[: first["src_start"]] + replacement + content[first["src_end"] :], target

    return remove_image_span(content, first["span_start"], first["span_end"]), None
