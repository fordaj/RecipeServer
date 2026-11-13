from pathlib import Path
from datetime import date, datetime, time, timezone
from html import escape
from functools import lru_cache
from .config import Configuration
from .image_handler import DEFAULT_TITLE, ImageToColorConverter, get_first_image_in_dir
import json, markdown, re, frontmatter
from textwrap import dedent
from bs4 import BeautifulSoup, Tag
from fractions import Fraction
from ._logger import logger
from .recipe_utils import (
    display_date,
    is_date_only,
    is_finite_rating_score,
    iter_valid_rating_entries,
    json_default,
    parse_metadata_datetime,
    slug_to_title,
)
from coloraide import Color
from importlib.metadata import version

VERSION = version("recipeserver")

# TODO: Move to definitions.py
_UNIT_ALIASES = {
    "tablespoons": "tbsp",
    "tablespoon": "tbsp",
    "teaspoons": "tsp",
    "teaspoon": "tsp",
    "cups": "cup",
    "milliliters": "mL",
    "milliliter": "mL",
    "ml": "mL",
    "l": "L",
    "lbs": "lb",
    "ounces": "oz",
    "ounce": "oz",
    "grams": "g",
    "gram": "g",
}

FILE_PATH = Path(__file__)
RECIPE_SCALER_HTML = FILE_PATH.parent / "assets" / "recipe-scaler.html"
GAUGE_SVG = FILE_PATH.parent / "assets" / "gauge.svg"
CHEF_HAT_SVG = FILE_PATH.parent / "assets" / "chef-hat.svg"
POT_SVG = FILE_PATH.parent / "assets" / "cooking-pot.svg"
TAG_SVG = FILE_PATH.parent / "assets" / "tag.svg"
QUILL_SVG = FILE_PATH.parent / "assets" / "quill.svg"
UTENSILS_SVG = FILE_PATH.parent / "assets" / "utensils.svg"
PIN_SVG = FILE_PATH.parent / "assets" / "pin.svg"
BOOK_SVG = FILE_PATH.parent / "assets" / "book.svg"
AI_SVG = FILE_PATH.parent / "assets" / "ai.svg"
USER_SVG = FILE_PATH.parent / "assets" / "user.svg"
USER_ROUND_SVG = FILE_PATH.parent / "assets" / "user-round.svg"
LINK_SVG = FILE_PATH.parent / "assets" / "link.svg"
NOTEBOOK_SVG = FILE_PATH.parent / "assets" / "notebook.svg"
PENCIL_SVG = FILE_PATH.parent / "assets" / "pencil.svg"
PLUS_SVG = FILE_PATH.parent / "assets" / "plus.svg"
ARCHIVE_SVG = FILE_PATH.parent / "assets" / "archive.svg"
INFO_SVG = FILE_PATH.parent / "assets" / "info.svg"


@lru_cache(maxsize=None)
def _read_svg(asset_path: Path) -> str:
    return asset_path.read_text(encoding="utf-8")


def _icon_html(asset_path: Path, class_name: str | None = None) -> str:
    """Return the SVG from an assets file, optionally overriding its class."""
    svg = BeautifulSoup(_read_svg(asset_path), "html.parser").find("svg")
    if svg is None:
        raise ValueError(f"No SVG element found in {asset_path}")
    if class_name is not None:
        svg["class"] = [class_name]
    return str(svg)


CSS_PATH = "/assets/style.css"
DEFINITIONS_CSS_PATH = "/assets/definitions.css"
RECIPE_JS = "/assets/recipe.js"
RECIPE_SCALER_CSS = "/assets/recipe-scaler.css"
RECIPE_EDITOR_JS = "/assets/recipe-editor/recipe-editor.js"
RECIPE_EDITOR_CSS = "/assets/recipe-editor/recipe-editor.css"
METADATA_PICKER_JS = "/assets/recipe-editor/metadata-picker.js"
AI_PROGRESS_JS = "/assets/recipe-editor/ai-progress.js"
RECIPE_SCALER_JS = "/assets/recipe-scaler.js"
COMMENTS_CSS = "/assets/comments.css"
COMMENTS_JS = "/assets/comments.js"
RATINGS_CSS = "/assets/ratings.css"
RATINGS_JS = "/assets/ratings.js"
RECIPE_FEEDBACK_JS = "/assets/recipe-feedback.js"
TIME_JS = "/assets/time.js"
ICONS_JS = "/assets/icons.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

KATEX = """
<link rel="stylesheet" href="/assets/katex/dist/katex.min.css">
<script defer src="/assets/katex/dist/katex.min.js"></script>
<script defer src="/assets/katex/dist/contrib/auto-render.min.js"></script>
<script defer src="/assets/katex-init.js"></script>
"""

HOME_PAGE_ICON_HTML = f"""
<a href="/index.html" class="recipe-home">
    {_icon_html(NOTEBOOK_SVG, "recipe-icon")}
</a>
"""

EDIT_RECIPE_HTML = f"""
<button id="edit-recipe"class="recipe-home" type="button" aria-label="Edit recipe" title="Edit recipe">
    {_icon_html(PENCIL_SVG, "recipe-icon")}
</button>
"""


def dark_mode_color(hex_color):
    color = Color(hex_color).convert("oklch")
    L, C, H = color.coords()

    # Map lightness into a brighter range for dark backgrounds.
    new_L = 0.65 + (1.0 - L) * 0.20

    result = Color("oklch", [new_L, C, H])
    result = result.convert("srgb").fit()

    return result.to_string(hex=True)


def _as_list(value: object) -> list:
    """Return metadata values as a list, accepting scalar strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


class MarkdownToHTMLConverter:
    def __init__(self, cfg: Configuration):
        self.cfg = cfg
        self.metadata: dict[str, object] = {}
        self.metadata_json: str = ""
        self.heading_color: str = getattr(cfg, "food_color", None) or DEFAULT_TITLE
        self.title: str = ""

    def get_doc_specific_overrides(self) -> str:
        return dedent(f"""
            <style>
                :root {{
                    --food-color: {self.heading_color};
                }}
                @media (prefers-color-scheme: dark) {{
                    :root {{
                        --food-color: {dark_mode_color(self.heading_color)};
                    }}
                }}

                .recipe-icon {{
                    color: var(--food-color);
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: var(--food-color);
                }}
            </style>
        """)

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

    def _break_up_div_comments(self, markdown: list[str]) -> None:
        for i, line in enumerate(markdown):
            if (":::" in line or "///" in line) and ("<!--" in line):
                # Add a newline before the comment
                markdown[i] = line.replace("<!--", "\n<!--")

    def _preprocess(self, content: list[str]) -> None:
        self._break_up_div_comments(content)

    @staticmethod
    def _get_sanitized_unit(unit: str) -> str:
        normalized = unit.strip().lower()
        return _UNIT_ALIASES.get(normalized, unit.strip())

    @staticmethod
    def _quantity_amount_to_float(amount: str) -> float:
        """Convert a number, fraction, or mixed number string to a float."""
        parts = amount.split()
        if len(parts) == 2:
            return float(Fraction(parts[0])) + float(Fraction(parts[1]))
        return float(Fraction(amount))

    @classmethod
    def _parse_quantity_code(cls, value: str) -> tuple[float, str, float | None] | None:
        """Parse an inline quantity such as ``1 1/2 tbsp`` or ``1-2 cups``.

        Returns ``(start, unit, end)`` where ``end`` is set for ranges.
        """
        value = value.strip()
        if not value:
            return None

        number = r"(?:\d+/\d+|\d+(?:\.\d+)?)"
        mixed_number = rf"(?:\d+\s+\d+/\d+|{number})"

        # Range: "1-2 tbsp", "1/2-3/4 tsp", "1 1/2 - 2 1/2 tbsp"
        ranged = re.fullmatch(
            rf"({mixed_number})\s*[-–—]\s*({mixed_number})\s*(.*)",
            value,
        )
        if ranged:
            start, end, unit = ranged.groups()
            return (
                cls._quantity_amount_to_float(start),
                unit.strip(),
                cls._quantity_amount_to_float(end),
            )

        # Mixed number: "1 1/2 tbsp"
        mixed = re.fullmatch(rf"(\d+)\s+(\d+/\d+)\s*(.*)", value)
        if mixed:
            whole, fraction, unit = mixed.groups()
            return (
                float(Fraction(whole)) + float(Fraction(fraction)),
                unit.strip(),
                None,
            )

        # Single number/fraction with optional attached or spaced unit
        single = re.fullmatch(rf"({number})\s*(.*)", value)
        if single:
            amount, unit = single.groups()
            return float(Fraction(amount)), unit.strip(), None

        return None

    def _convert_quantity_code_spans(self, soup: BeautifulSoup) -> None:
        """Replace inline ``<code>`` quantities with scaler ``<span>`` elements."""
        for code in soup.find_all("code"):
            parsed = self._parse_quantity_code(code.get_text(strip=True))
            if parsed is None:
                continue

            quantity, unit, quantity_end = parsed
            unit = self._get_sanitized_unit(unit)

            span = soup.new_tag("span")
            span["class"] = "quantity"
            span["data-quantity"] = str(quantity)
            span["data-unit"] = unit

            if quantity_end is not None:
                span["data-quantity-end"] = str(quantity_end)

            code.replace_with(span)

    def _group_recipe_meta_terms(self, soup: BeautifulSoup) -> None:
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

    def _enable_checkbox_inputs(self, soup: BeautifulSoup) -> None:
        # Remove the "disabled" attribute from <input checkbox> elements
        for checkbox in soup.select('input[type="checkbox"]'):
            checkbox.attrs.pop("disabled", None)

    def _append_svg_icon(
        self,
        parent: Tag,
        path: Path,
    ) -> None:
        svg = BeautifulSoup(_read_svg(path), "html.parser").find("svg")

        if svg is None:
            raise ValueError(f"No SVG element found in {path}")

        svg["aria-hidden"] = "true"
        svg["focusable"] = "false"

        parent.append(svg)

    def _build_recipe_overview(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        """Build the overview rows shown above the hero image."""
        overview = soup.new_tag("div", attrs={"class": "recipe-overview"})

        primary = self._build_overview_primary_row(metadata, soup)
        if primary.contents:
            overview.append(primary)

        secondary = self._build_overview_secondary_row(metadata, soup)
        if secondary.contents:
            overview.append(secondary)

        tertiary = self._build_overview_tertiary_row(metadata, soup)
        if tertiary.contents:
            overview.append(tertiary)

        return overview if overview.contents else None

    def _build_overview_primary_row(self, metadata: dict, soup: BeautifulSoup) -> Tag:
        """Build the row for rating, yield, difficulty, and meal type."""
        primary = soup.new_tag("div", attrs={"class": "recipe-overview__primary"})

        self._append_overview_rating(primary, metadata, soup)
        self._append_overview_icon_value(
            primary,
            soup,
            icon_path=CHEF_HAT_SVG,
            class_name="recipe-overview__makes",
            value=self._first_scalar(metadata.get("makes")),
            formatter=lambda value: f"x{value}",
            tag_name="button",
            attrs={
                "type": "button",
                "class": "recipe-overview__makes",
                "aria-label": "Record that you made this recipe",
                "title": "I made this!",
            },
            data_attrs=lambda value: {"makes": str(value)},
        )
        self._append_overview_icon_value(
            primary,
            soup,
            icon_path=GAUGE_SVG,
            class_name="recipe-overview__difficulty",
            value=self._first_scalar(metadata.get("difficulty")),
            formatter=lambda value: f"{value}/10",
        )
        self._append_overview_icon_value(
            primary,
            soup,
            icon_path=UTENSILS_SVG,
            class_name="recipe-overview__meals",
            value=_as_list(metadata.get("meals")),
            formatter=lambda values: ", ".join(str(value) for value in values),
        )

        return primary

    def _append_overview_rating(self, container: Tag, metadata: dict, soup: BeautifulSoup) -> None:
        rating_scores = [score for _, score in iter_valid_rating_entries(metadata.get("ratings"))]
        if not rating_scores:
            return

        average = sum(rating_scores) / len(rating_scores)
        rating = soup.new_tag("span", attrs={"class": "recipe-overview__rating"})
        rating.string = f"★ {average:.1f}/10"
        container.append(rating)

    def _append_overview_icon_value(
        self,
        container: Tag,
        soup: BeautifulSoup,
        *,
        icon_path: Path,
        class_name: str,
        value: object,
        formatter,
        tag_name: str = "span",
        attrs: dict[str, str] | None = None,
        data_attrs: object = None,
    ) -> None:
        """Append an icon+text overview item when *value* is present."""
        if value is None or value == "" or value == []:
            return

        item_attrs = dict(attrs) if attrs is not None else {"class": class_name}
        item = soup.new_tag(tag_name, attrs=item_attrs)
        if data_attrs is not None:
            for name, attr_value in data_attrs(value).items():
                item[f"data-{name}"] = attr_value
        self._append_svg_icon(item, icon_path)
        text = soup.new_tag("span", attrs={"class": "recipe-overview__value"})
        text.string = formatter(value)
        item.append(text)
        container.append(item)

    def _build_overview_secondary_row(self, metadata: dict, soup: BeautifulSoup) -> Tag:
        """Build the row for status, cuisine, categories, and tags."""
        secondary = soup.new_tag("div", attrs={"class": "recipe-overview__secondary"})

        detail_icons = {
            "status": INFO_SVG,
            "cuisine": PIN_SVG,
            "categories": POT_SVG,
            "tags": TAG_SVG,
        }

        for key in ("status", "cuisine", "categories", "tags"):
            values = _as_list(metadata.get(key))
            if key == "status":
                values = values[:1]
            if key == "categories" and not values:
                values = _as_list(metadata.get("category"))
            if not values:
                continue

            group = soup.new_tag("span", attrs={"class": f"recipe-overview__{key}"})
            self._append_svg_icon(group, detail_icons[key])

            for index, value in enumerate(values):
                if index:
                    group.append(", ")
                label = soup.new_tag("span")
                label.string = str(value)
                group.append(label)

            secondary.append(group)

        return secondary

    def _build_overview_tertiary_row(self, metadata: dict, soup: BeautifulSoup) -> Tag:
        """Build the third overview row, reserved for the archived badge."""
        tertiary = soup.new_tag("div", attrs={"class": "recipe-overview__tertiary"})

        if metadata.get("archived") is True:
            self._append_overview_icon_value(
                tertiary,
                soup,
                icon_path=ARCHIVE_SVG,
                class_name="recipe-overview__archived",
                value="Archived",
                formatter=lambda value: str(value),
            )

        return tertiary

    @staticmethod
    def _first_scalar(value: object) -> object:
        """Return a scalar metadata value, unwrapping a single-item list."""
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def _inject_recipe_overview(self, soup: BeautifulSoup) -> None:
        title = soup.find("h1")
        if title is None:
            return

        hero = title.find_next("img")
        if hero is None:
            return

        overview = self._build_recipe_overview(self.metadata, soup)
        if overview:
            hero.parent.insert_before(overview)

    def _build_recipe_contributor(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        contributor = metadata.get("contributor", "")

        if isinstance(contributor, (list, tuple)):
            contributor = ", ".join(str(value) for value in contributor if value)

        if not isinstance(contributor, str):
            contributor = str(contributor or "")

        contributor = contributor.strip()

        if not contributor:
            return None

        created_on_value = metadata.get("createdOn")
        created_on = parse_metadata_datetime(created_on_value)

        item = soup.new_tag(
            "div",
            attrs={"class": "recipe-contributor"},
        )

        self._append_svg_icon(item, QUILL_SVG)

        label = soup.new_tag("span")
        label.string = f"by {contributor}"

        if created_on:
            separator = soup.new_tag(
                "span",
                attrs={"class": "recipe-meta__separator"},
            )
            separator.string = "·"
            label.append(separator)

            if is_date_only(created_on_value):
                time_attrs = {"datetime": created_on.date().isoformat()}
            else:
                time_attrs = {
                    "datetime": created_on.isoformat(),
                    "data-local-time": "true",
                }

            time_element = soup.new_tag("time", attrs=time_attrs)
            time_element.string = display_date(created_on)
            label.append(time_element)

        item.append(label)

        return item

    def _inject_recipe_contributor(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        contributor = self._build_recipe_contributor(self.metadata, soup)
        if contributor:
            main.append(contributor)

    def _build_recipe_sources(self, metadata: dict, soup: BeautifulSoup) -> Tag | None:
        sources = metadata.get("source")

        if isinstance(sources, dict):
            sources = [sources]
        elif not isinstance(sources, list):
            sources = []

        container = soup.new_tag(
            "div",
            attrs={"class": "recipe-sources"},
        )

        for source in sources:
            if not isinstance(source, dict):
                continue

            source_format = str(source.get("format") or "").lower()
            title = str(source.get("title") or "").strip()
            author = str(source.get("author") or "").strip()
            url = str(source.get("url") or "").strip()

            if source_format == "website":
                title = title or str(source.get("company") or "").strip()
                icon = LINK_SVG
            elif source_format == "book":
                icon = BOOK_SVG
            elif source_format == "ai":
                icon = AI_SVG
            else:
                icon = USER_SVG

            if not title:
                continue

            item = soup.new_tag(
                "span",
                attrs={"class": "recipe-sources__item"},
            )

            self._append_svg_icon(item, icon)

            if source_format == "website" and url:
                label = soup.new_tag(
                    "a",
                    href=url,
                    attrs={
                        "target": "_blank",
                        "rel": "noopener noreferrer",
                    },
                )
            else:
                label = soup.new_tag("span")

            label.string = title
            item.append(label)

            if author:
                author_group = soup.new_tag(
                    "span",
                    attrs={"class": "recipe-sources__author"},
                )

                self._append_svg_icon(author_group, USER_SVG)

                label = soup.new_tag("span")
                label.string = author
                author_group.append(label)

                item.append(author_group)

            container.append(item)

        return container if container.contents else None

    def _inject_recipe_sources(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        sources = self._build_recipe_sources(self.metadata, soup)
        if sources:
            main.append(sources)

    def _build_recipe_version(self, metadata: dict, soup: BeautifulSoup) -> Tag:
        version_element = soup.new_tag(
            "div",
            attrs={"class": "recipe-version recipe-extras"},
        )

        self._append_svg_icon(version_element, TAG_SVG)

        label = soup.new_tag("span")

        updated_on_value = metadata.get("updatedOn")
        updated_on = parse_metadata_datetime(updated_on_value)
        label.append(f"v{VERSION}")

        if updated_on:
            separator = soup.new_tag(
                "span",
                attrs={"class": "recipe-meta__separator"},
            )
            separator.string = "·"
            label.append(separator)

            if is_date_only(updated_on_value):
                time_attrs = {"datetime": updated_on.date().isoformat()}
            else:
                time_attrs = {
                    "datetime": updated_on.isoformat(),
                    "data-local-time": "true",
                    "data-time-prefix": "Edited ",
                }

            time_element = soup.new_tag("time", attrs=time_attrs)
            time_element.string = f"Edited {display_date(updated_on)}"
            label.append(time_element)

        version_element.append(label)

        return version_element

    def _inject_recipe_version(self, soup: BeautifulSoup) -> None:
        main = soup.find("main", class_="recipe")
        if main is None:
            return

        version_element = self._build_recipe_version(self.metadata, soup)
        main.append(version_element)

    def _postprocess(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        self._convert_quantity_code_spans(soup)
        self._group_recipe_meta_terms(soup)
        self._enable_checkbox_inputs(soup)
        self._inject_recipe_overview(soup)
        self._inject_recipe_contributor(soup)
        self._inject_recipe_sources(soup)
        self._inject_recipe_version(soup)

        # The HTML <title> uses the raw heading/front matter value (escaped) for
        # fidelity. Keep the converter's title as the rendered heading text so
        # callers get the same plain text the page displays.
        heading = soup.find("h1")
        if heading is not None:
            rendered_title = heading.get_text(" ", strip=True)
            if rendered_title:
                self.title = rendered_title

        return str(soup)

    def _get_comments_html(self, has_comments: bool = False) -> str:
        empty_class = "" if has_comments else " is-empty"
        return dedent(f"""
            <section class="recipe-comments{empty_class} recipe-extras" id="recipe-comments">
                <h2 class="recipe-comments__heading">
                    <span>Comments</span>
                    <button class="recipe-comments__add" type="button" aria-label="Add a comment" aria-expanded="false">
                    {_icon_html(PLUS_SVG)}
                    </button>
                </h2>
                <form id="recipe-comment-form" class="recipe-comment-form" hidden>
                <div class="recipe-comment__avatar recipe-comment-form__avatar" aria-hidden="true">
                    {_icon_html(USER_ROUND_SVG)}
                </div>

                <div class="recipe-comment__content">
                    <div class="recipe-comment__meta">
                    <input id="comment-author" class="recipe-comment__author-input" type="text" placeholder="Your name" aria-label="Your name" required/>
                    <span class="recipe-comment__date">Posting today</span>
                    </div>

                    <textarea id="comment-text" class="recipe-comment__text-input" placeholder="Write a comment..." aria-label="Comment" rows="3" required ></textarea>

                    <div class="recipe-comment__actions recipe-comment-form__actions">
                    <button id="cancel-comment" type="button">Cancel</button>
                    <button id="save-comment" type="submit">Post comment</button>
                    </div>

                    <p id="comment-status" role="status" aria-live="polite"></p>
                </div>
                </form>
                <div class="recipe-comments__list" id="comment-list"></div>
            </section>
        """).strip()

    def _get_ratings_html(self, has_ratings: bool = False) -> str:
        empty_class = "" if has_ratings else " is-empty"
        return dedent(f"""
            <section class="recipe-ratings{empty_class} recipe-extras" id="recipe-ratings">
                <h2 class="recipe-ratings__heading">
                    <span>Ratings</span>
                    <button class="recipe-ratings__add" type="button" aria-label="Add a rating" aria-expanded="false">
                    {_icon_html(PLUS_SVG)}
                    </button>
                </h2>
                <form id="recipe-rating-form" class="recipe-rating-form" hidden>
                    <div class="recipe-rating__avatar recipe-rating-form__avatar" aria-hidden="true">
                        {_icon_html(USER_ROUND_SVG)}
                    </div>
                    <div class="recipe-rating-form__content">
                        <div class="recipe-rating-form__meta">
                            <input id="rating-author" type="text" placeholder="Your name" aria-label="Your name" maxlength="100" required />
                        </div>
                        <div class="recipe-rating__meter recipe-rating-form__meter">
                            <input id="rating-score" type="text" inputmode="decimal" maxlength="16" value="5" aria-label="Rating out of 10" required />
                            <span class="recipe-rating__stars" role="img" aria-label="5 out of 10">★★★★★</span>
                            <output id="rating-score-value" class="recipe-rating__score">5/10</output>
                        </div>
                        <div class="recipe-rating__actions recipe-rating-form__actions">
                            <button id="cancel-rating" type="button">Cancel</button>
                            <button id="save-rating" type="submit">Post rating</button>
                        </div>
                        <p id="rating-status" role="status" aria-live="polite"></p>
                    </div>
                </form>
                <div class="recipe-ratings__list" id="rating-list"></div>
            </section>
        """).strip()

    def convert(self, markdown_file: Path, html_file: Path):
        logger.file(f"Converting {markdown_file.relative_to(self.cfg.source_directory)}")

        # ----- Load and parse source ----- #
        markdown_lines = markdown_file.read_text(encoding="UTF-8", newline="\n").splitlines()
        self._preprocess(markdown_lines)

        post = frontmatter.loads("\n".join(markdown_lines))
        self.metadata = post.metadata

        # Resolve the page title from the Markdown heading, front matter, or
        # directory name. The raw source title is used for the HTML <title>
        # element; _postprocess updates self.title to the rendered heading text.
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
        html = self._build_recipe_html(
            source_title=source_title,
            body=body,
            ratings_html=self._get_ratings_html(has_ratings),
            comments_html=self._get_comments_html(has_comments),
        )
        html = self._postprocess(html)

        html_file.write_text(html, encoding="UTF-8", newline="\n")
        logger.debug(f'Created "{html_file}"')  # TODO get_pretty_path_str

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
        return any(is_finite_rating_score(rating.get("rating")) for rating in _as_list(metadata.get("ratings")) if isinstance(rating, dict))

    @staticmethod
    def _has_comments(metadata: dict[str, object]) -> bool:
        return any(isinstance(comment, dict) for comment in _as_list(metadata.get("comments")))

    def _build_recipe_html(
        self,
        *,
        source_title: str,
        body: str,
        ratings_html: str,
        comments_html: str,
    ) -> str:
        """Render the full recipe page HTML shell."""
        return dedent(f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{escape(source_title)}</title>
            <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
            <link rel="stylesheet" href="{DEFINITIONS_CSS_PATH}">
            <link rel="stylesheet" href="{CSS_PATH}">
            <link rel="stylesheet" href="{RECIPE_SCALER_CSS}">
            <link rel="stylesheet" href="{RECIPE_EDITOR_CSS}">
            <link rel="stylesheet" href="{COMMENTS_CSS}">
            <link rel="stylesheet" href="{RATINGS_CSS}">
            {self.get_doc_specific_overrides()}
            {KATEX}
        </head>
        <body>
            <script id="recipe-metadata" type="application/json">{self.metadata_json}</script>
            <main class="recipe">
                <header class="recipe-header">
                    {HOME_PAGE_ICON_HTML}
                    {RECIPE_SCALER_HTML.read_text(encoding="UTF-8", newline="\n")}
                    {EDIT_RECIPE_HTML}
                </header>
                {body}
                {ratings_html}
                {comments_html}
            </main>
            <script defer src="{TIME_JS}"></script>
            <script defer src="{ICONS_JS}"></script>
            <script defer src="{RECIPE_JS}"></script>
            <script defer src="{RECIPE_SCALER_JS}"></script>
            <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
            <script defer src="{RECIPE_FEEDBACK_JS}"></script>
            <script defer src="{COMMENTS_JS}"></script>
            <script defer src="{RATINGS_JS}"></script>
            <script defer src="{METADATA_PICKER_JS}"></script>
            <script defer src="{AI_PROGRESS_JS}"></script>
            <script defer src="{RECIPE_EDITOR_JS}"></script>
        </body>
        </html>
        """)

    def _lint_metadata(self, markdown_file: Path):
        has_meal_or_cuisine = "meals" in self.metadata or "cuisine" in self.metadata
        if not has_meal_or_cuisine:
            logger.warning(f'[MetadataWarning]{markdown_file}: Missing key "meals:" or "cuisine:"')

    def lint_html(self, html: str, html_file: Path):
        for i, line in enumerate(html.splitlines()):
            if "<code>" in line and "</code>" in line:
                logger.warning(f'Unprocessed quantity in "{html_file}:{i+1}"\n{line}')
