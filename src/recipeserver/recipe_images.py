"""Edit image references inside recipe Markdown.

The image APIs rename, delete, and choose the hero image by rewriting the
Markdown source. Those are text rules, not HTTP rules, so they live here
independently of the request handler that calls them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import PureWindowsPath
from urllib.parse import quote, unquote

from PIL import Image, UnidentifiedImageError

from .image_handler import IMAGE_EXTENSIONS
from .recipe_utils import is_windows_reserved_name

_SVG_BLOCKED_TAGS = frozenset({"script", "foreignobject"})

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


# ----- Uploaded image validation ----- #


def _xml_local_name(name: str) -> str:
    """Strip any XML namespace from a tag or attribute name."""
    return name.rsplit("}", 1)[-1].lower()


def validate_image_filename(filename: str) -> None:
    windows_path = PureWindowsPath(filename)
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or windows_path.name != filename
        or any(ord(character) < 32 or character in '<>:"|?*' for character in filename)
        or filename.endswith((".", " "))
    ):
        raise ValueError("Invalid image filename")

    if is_windows_reserved_name(filename.split(".", 1)[0]):
        raise ValueError("Invalid image filename")


def validate_svg_attribute(filename: str, attribute: str, value: str) -> None:
    """Reject event-handler attributes and external references in an SVG."""
    attr_name = _xml_local_name(attribute)
    if attr_name.startswith("on"):
        raise ValueError(f"SVG contains unsupported active content: {filename}")

    if attr_name not in {"href", "style"}:
        return

    lowered_value = value.lower()
    references_external_url = "url(" in lowered_value and "url(#" not in lowered_value
    references_external_href = attribute.lower().endswith("href") and not value.startswith("#")
    if references_external_url or references_external_href:
        raise ValueError(f"SVG contains unsupported external content: {filename}")


def validate_image_name(name: str, *, field: str) -> str:
    """Validate a bare image filename (no directories) for the rename API."""
    try:
        validate_image_filename(name)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc
    if PureWindowsPath(name).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f"{field} must keep a supported image extension ({', '.join(sorted(IMAGE_EXTENSIONS))})")
    return name


def validate_svg_content(filename: str, content: bytes) -> None:
    if b"<!doctype" in content.lower():
        raise ValueError(f"Invalid SVG image: {filename}")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG image: {filename}") from exc
    if _xml_local_name(root.tag) != "svg":
        raise ValueError(f"Invalid SVG image: {filename}")

    for element in root.iter():
        if _xml_local_name(element.tag) in _SVG_BLOCKED_TAGS:
            raise ValueError(f"SVG contains unsupported active content: {filename}")
        for attribute, value in element.attrib.items():
            validate_svg_attribute(filename, attribute, value)


def validate_image_content(filename: str, content: bytes) -> None:
    extension = PureWindowsPath(filename).suffix.lower()
    if extension == ".svg":
        validate_svg_content(filename, content)
        return

    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Invalid image file: {filename}") from exc
