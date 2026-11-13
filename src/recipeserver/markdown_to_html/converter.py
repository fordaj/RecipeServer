"""Render a recipe Markdown file to a full HTML page.

The pipeline runs in stages: load and parse the source, resolve appearance
and metadata, render the Markdown body, assemble the page shell, and then
postprocess the assembled document (quantity spans, metadata definition
list grouping, overview/contributor/sources/version injection). The stages
live in their own modules; this module orchestrates them.
"""

from pathlib import Path

import json
import re

import frontmatter
import markdown
from bs4 import BeautifulSoup, Tag

from .._logger import logger
from ..config import Configuration
from ..image_handler import DEFAULT_TITLE, ImageToColorConverter, get_first_image_in_dir
from ..metadata_linter import lint_recipe_metadata
from ..recipe_utils import as_list, is_finite_rating_score, json_default, slug_to_title
from . import extras, feedback, overview, page, quantities


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self.metadata: dict[str, object] = {}
        self.metadata_json: str = ""
        self.heading_color: str = getattr(cfg, "food_color", None) or DEFAULT_TITLE
        self.title: str = ""
        # Read the scaler markup once so convert() performs no hidden file I/O.
        self._recipe_scaler_html = page.RECIPE_SCALER_HTML.read_text(encoding="utf-8", newline="\n")

    @staticmethod
    def _get_title_from_markdown_content(content: list[str]) -> str | None:
        """Return the first level-one heading, ignoring fenced code blocks."""
        in_fence = False

        for line in content:
            stripped = line.lstrip()

            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue

            if in_fence:
                continue

            match = re.match(r"^ {0,3}#\s+(.*?)\s*#*\s*$", line)
            if match and match.group(1).strip():
                return match.group(1).strip()

        return None

    def convert(self, markdown_file: Path, html_file: Path):
        logger.file(f"Converting {markdown_file.relative_to(self.cfg.source_directory)}")

        # ----- Load and parse source ----- #
        markdown_lines = markdown_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        _preprocess(markdown_lines)

        post = frontmatter.loads("\n".join(markdown_lines))
        self.metadata = post.metadata

        # Resolve the page title from the Markdown heading, front matter, or
        # directory name. The raw source title is used for the HTML <title>
        # element; _postprocess returns the rendered heading text, which the
        # caller stores on self.title.
        source_title = (
            self._get_title_from_markdown_content(post.content.splitlines())
            or str(post.metadata.get("title") or "").strip()
            or slug_to_title(markdown_file.parent.name)
        )
        self.title = source_title

        # ----- Resolve appearance and metadata ----- #
        self.heading_color = self._resolve_heading_color(markdown_file.parent)
        self._lint_metadata(markdown_file)
        self.metadata_json = self._serialize_metadata_json(self.metadata)

        has_ratings = self._has_valid_ratings(self.metadata)
        has_comments = self._has_comments(self.metadata)

        # ----- Render Markdown body ----- #
        markdown_renderer = markdown.Markdown(
            extensions=[
                "pymdownx.extra",
                "pymdownx.blocks.html",
                "pymdownx.tasklist",
                "pymdownx.arithmatex",
            ]
        )
        body = markdown_renderer.convert(post.content)

        # ----- Build, postprocess, and write HTML ----- #
        html = page.build_recipe_html(
            source_title=source_title,
            heading_color=self.heading_color,
            metadata_json=self.metadata_json,
            recipe_scaler_html=self._recipe_scaler_html,
            body=body,
            ratings_html=feedback.ratings_html(has_ratings),
            comments_html=feedback.comments_html(has_comments),
        )
        html, rendered_title = self._postprocess(html)
        if rendered_title:
            # Keep the converter's title as the rendered heading text, so
            # callers get the same plain text the page displays.
            self.title = rendered_title

        html_file.write_text(html, encoding="UTF-8", newline="\n")
        logger.debug(f'Created "{html_file}"')

        self.lint_html(html, html_file)

    def _resolve_heading_color(self, recipe_directory: Path) -> str:
        """Return an accent color derived from the recipe's hero image.

        Falls back to the configured food color when there is no usable
        hero image.
        """
        fallback = getattr(self.cfg, "food_color", None) or DEFAULT_TITLE
        image = get_first_image_in_dir(recipe_directory)
        if not image:
            return fallback

        logger.file(f"Found image: {image}")
        try:
            return ImageToColorConverter().get_hex_color_from_image(image)
        except (OSError, ValueError) as exc:
            logger.warning(f'Could not derive an accent color from "{image}": {exc}')
            return fallback

    @staticmethod
    def _serialize_metadata_json(metadata: dict[str, object]) -> str:
        """Serialize metadata for embedding in a script tag."""
        # Sanitize "<" so embedded JSON cannot break out of the script element.
        return json.dumps(metadata, default=json_default).replace("<", "\\u003c")

    @staticmethod
    def _has_valid_ratings(metadata: dict[str, object]) -> bool:
        return any(is_finite_rating_score(rating.get("rating")) for rating in as_list(metadata.get("ratings")) if isinstance(rating, dict))

    @staticmethod
    def _has_comments(metadata: dict[str, object]) -> bool:
        return any(isinstance(comment, dict) for comment in as_list(metadata.get("comments")))

    def _postprocess(self, content: str) -> tuple[str, str | None]:
        """Postprocess the assembled document.

        Returns the final HTML and the rendered heading text (or ``None``
        when the document has no level-one heading) so callers can decide
        what to store on ``self.title``.
        """
        soup = BeautifulSoup(content, "html.parser")
        quantities.convert_quantity_code_spans(soup)
        _group_recipe_meta_terms(soup)
        _enable_checkbox_inputs(soup)
        overview.inject_recipe_overview(soup, self.metadata)
        extras.inject_recipe_contributor(soup, self.metadata)
        extras.inject_recipe_sources(soup, self.metadata)
        extras.inject_recipe_version(soup, self.metadata)

        # The HTML <title> uses the raw heading/front matter value (escaped) for
        # fidelity; only the returned title carries the rendered heading text.
        heading = soup.find("h1")
        rendered_title = heading.get_text(" ", strip=True) if heading is not None else None

        return str(soup), rendered_title or None

    def _lint_metadata(self, markdown_file: Path) -> None:
        for warning in lint_recipe_metadata(self.metadata):
            logger.warning(f'[MetadataWarning]{markdown_file}: {warning["message"]}')

    def lint_html(self, html: str, html_file: Path):
        for i, line in enumerate(html.splitlines()):
            if "<code>" in line and "</code>" in line:
                logger.warning(f'Unprocessed quantity in "{html_file}:{i+1}"\n{line}')


# ----- Markdown source preprocessing ----- #


def _preprocess(markdown_lines: list[str]) -> None:
    _break_up_div_comments(markdown_lines)


def _break_up_div_comments(markdown_lines: list[str]) -> None:
    for i, line in enumerate(markdown_lines):
        if (":::" in line or "///" in line) and ("<!--" in line):
            # Add a newline before the comment
            markdown_lines[i] = line.replace("<!--", "\n<!--")


# ----- Soup surgery ----- #


def _group_recipe_meta_terms(soup: BeautifulSoup) -> None:
    """Group each ``dt`` with its following ``dd`` in recipe metadata.

    Markdown definition lists render as a flat ``dt``/``dd`` sequence,
    which makes every term and value separately wrappable: a ``dt``
    can end one line while its ``dd`` starts the next. Wrapping each
    term together with its description in a single
    ``.recipe-meta__group`` element (``dt`` first, ``dd`` after it,
    i.e. above it once displayed as blocks) lets the group's CSS
    treat the pair as one inline unit that wraps as a group. Runs of
    terms followed by a run of descriptions (multiple ``dt`` sharing
    ``dd`` values, or one ``dt`` with multiple ``dd`` values) stay in
    the same group so the semantics of the definition list are kept.
    A ``dd`` without a preceding ``dt`` forms a group of its own.
    """

    def group_terms(container: Tag) -> None:
        terms = [child for child in container.children if getattr(child, "name", None) in ("dt", "dd")]
        if not terms:
            return

        groups: list[list[Tag]] = []
        current: list[Tag] = []

        for term in terms:
            if term.name == "dt" and any(item.name == "dd" for item in current):
                groups.append(current)
                current = [term]
            else:
                current.append(term)

        if current:
            groups.append(current)

        for term in terms:
            term.extract()

        for group in groups:
            wrapper = soup.new_tag(
                "div",
                attrs={"class": "recipe-meta__group"},
            )
            for term in group:
                wrapper.append(term)
            container.append(wrapper)

    for container in soup.select(".recipe-meta dl"):
        group_terms(container)

    # Authors may also write dt/dd directly inside .recipe-meta
    # without a wrapping <dl>; group those too.
    for container in soup.select(".recipe-meta"):
        if container.find("dl", recursive=False) is None:
            group_terms(container)


def _enable_checkbox_inputs(soup: BeautifulSoup) -> None:
    # Remove the "disabled" attribute from <input checkbox> elements
    for checkbox in soup.select('input[type="checkbox"]'):
        checkbox.attrs.pop("disabled", None)
